"""Read-only, small-sample accounting export. No 1C documents are posted here."""
import csv
import io
import json
import uuid
from collections import defaultdict
from datetime import date
from decimal import Decimal
from xml.etree import ElementTree as ET
from zipfile import ZipFile, ZIP_DEFLATED

from django.db.models import Prefetch
from .financial_queries import with_financials
from .models import Contract, Payment

CENT = Decimal('0.01')
CARD = {'Тинькофф Интернет', 'Uniteller АББ Интернет', 'Терминал'}
SBP = {'СБП', 'Тинькофф QR', 'Сбербанк QR'}
BANK = {'Тинькофф р/с', 'Сбербанк р/с', 'Альфа Банк р/с', 'Счет', 'Счёт'}
EXCLUDED = {'Кредит', 'МИР', 'МИР туроператору'}
CLIENT_KINDS = ('customer', 'customer_refund')

LABELS = {
    'not_reached': 'Оплата не превысила себестоимость',
    'requires_review': 'Нужна проверка', 'in_period': 'В выбранном году',
    'outside_period': 'В другом году', 'bank_statement_only': 'Уже отражается выпиской банка',
    'excluded_method': 'Способ исключён из обмена', 'blocked': 'Нужно уточнение',
    'planned': 'В проекте операций', 'review': 'Нужна проверка',
    'offset_proposed': 'Пара зачёта предложена для подтверждения',
    'ambiguous_offset': 'Не найдена однозначная пара зачёта',
    'offset_counterpart_not_selected': 'Выберите второй договор зачёта',
    'manual': 'Ручная операция', 'offset': 'Зачёт',
    'cash_receipt': 'ПКО', 'cash_refund': 'РКО', 'draft': 'Проект',
    'confirm_pair': 'Подтвердить пару', 'requires_cash_analytics': 'Проверить кассу и субконто',
    'cash_contract_excluded': 'Договор с Касса наличные исключён',
    'cash_mixed_requires_review': 'Уточнить исключение наличных при смешанной оплате',
    'company_matching_not_agreed': 'Сопоставление юридического лица пока не согласовано',
    'missing_name': 'Не заполнен заказчик или туроператор',
    'invalid_payment_amount': 'Сумма финансовой строки должна быть положительной',
    'unmapped_method': 'Способ оплаты пока не сопоставлен',
    'shipment_requires_review': 'Проверить отгрузку: возврат, зачёт, неопределённый способ или неположительная комиссия/себестоимость',
    'duplicate_customer_names': 'Найдены разные карточки заказчика с одинаковым ФИО',
}


def label(code):
    return LABELS.get(code, code)


def money(value):
    return format(Decimal(value).quantize(CENT), '.2f')


def normalized_name(value):
    return ' '.join(value.split()).casefold()


def safe_csv(value):
    """Prevent spreadsheet formula execution in user-supplied text."""
    value = str(value)
    return "'" + value if value.lstrip().startswith(('=', '+', '-', '@')) else value


def csv_bytes(headers, rows):
    stream = io.StringIO(newline='')
    writer = csv.writer(stream, delimiter=';')
    writer.writerow(headers)
    for row in rows:
        writer.writerow([safe_csv(v) if isinstance(v, str) else v for v in row])
    return stream.getvalue().encode('utf-8-sig')


def operation_key(kind, *keys):
    # Compound keys don't depend on which side of a pair was selected first.
    return str(uuid.uuid5(uuid.NAMESPACE_URL, 'aborigen-crm/1c/v1/' + kind + '/' + '/'.join(sorted(map(str, keys)))))


def build_plan(contract_ids, year):
    ids = sorted(set(contract_ids))
    if not ids or len(ids) > 20:
        raise ValueError('Выберите от 1 до 20 договоров для теста.')
    if not 1900 <= year <= 2100:
        raise ValueError('Укажите год от 1900 до 2100.')
    payments = Payment.objects.select_related('method', 'legacy_payer', 'contract__customer').order_by('date', 'pk')
    contracts = list(with_financials(Contract.objects.filter(pk__in=ids)).select_related(
        'customer', 'operator', 'payment_method').order_by('date', 'pk').prefetch_related(Prefetch('payments', queryset=payments)))
    if len(contracts) != len(ids):
        raise ValueError('Один из выбранных договоров больше не существует.')
    plan = {'format': 'aborigen-crm-one-c-test', 'version': 1, 'year': year,
            'test_only': True, 'contracts': [], 'operations': [], 'issues': []}
    issues = plan['issues']
    offsets = []
    seen_names = defaultdict(set)
    for contract in contracts:
        key = str(contract.exchange_id)
        client = [p for p in contract.payments.all() if p.kind in CLIENT_KINDS]
        def issue(code, payment=None):
            issues.append({'code': code, 'contract': key, 'number': contract.number,
                           'payment': str(payment.exchange_id) if payment else ''})
        header_cash = contract.payment_method and contract.payment_method.name == 'Касса наличные'
        cash_payments = any(p.method.name == 'Касса наличные' for p in client)
        if header_cash or cash_payments:
            # Mixed/header-vs-payment trigger not agreed yet: withhold, never guess.
            issue('cash_contract_excluded' if header_cash and all(p.method.name == 'Касса наличные' for p in client)
                  else 'cash_mixed_requires_review')
            continue
        if contract.customer.kind != 'person':
            issue('company_matching_not_agreed')
            continue
        if not contract.customer.name.strip() or not contract.operator.name.strip():
            issue('missing_name')
            continue
        customer = {'id': str(contract.customer.exchange_id), 'name': contract.customer.name}
        seen_names[normalized_name(customer['name'])].add(customer['id'])
        record = {'id': key, 'number': contract.number, 'date': contract.date.isoformat(),
                  'customer': customer, 'operator': {'id': str(contract.operator.exchange_id), 'name': contract.operator.name},
                  'amount': money(contract.amount), 'cost': money(contract.cost),
                  'commission': money(contract.profit), 'currency': 'RUB',
                  'voucher_date': date(year, 12, 31).isoformat(), 'shipment_date': None,
                  'shipment_status': 'not_reached', 'payments': []}
        plan['contracts'].append(record)
        # Recognition must include the full history, even for a current-year payment on an old contract.
        balance = Decimal('0')
        crossed = None
        uncertain = False
        for payment in client:
            amount = payment.amount if payment.kind == 'customer' else -payment.amount
            method = payment.method.name
            if payment.amount <= 0:
                issue('invalid_payment_amount', payment); uncertain = True
            if payment.kind == 'customer_refund' or method == 'Зачет' or method == 'Зачёт':
                # Effect of returns/offsets on revenue recognition has not been agreed.
                uncertain = True
            if method not in CARD | SBP | BANK | EXCLUDED | {'Касса чек', 'Зачет', 'Зачёт'}:
                issue('unmapped_method', payment); uncertain = True
            balance += amount
            if crossed is None and amount > 0 and balance > contract.cost:
                crossed = payment.date
            if payment.date.year != year:
                continue
            payer = payment.payer
            item = {'id': str(payment.exchange_id), 'contract': key, 'date': payment.date.isoformat(),
                    'amount': money(amount), 'method': method,
                    'payer': {'id': str(payer.exchange_id), 'name': payer.name}, 'status': 'review'}
            record['payments'].append(item)
            if payment.amount <= 0:
                item['status'] = 'blocked'; continue
            if method in BANK:
                item['status'] = 'bank_statement_only'; continue
            if method in EXCLUDED:
                item['status'] = 'excluded_method'; continue
            if method in {'Зачет', 'Зачёт'}:
                offsets.append((payment, item)); continue
            debit = '57.1' if method in CARD else '57.2' if method in SBP else '50.1' if method == 'Касса чек' else ''
            if not debit:
                item['status'] = 'blocked'; continue
            cash = method == 'Касса чек'
            item['status'] = 'planned'
            plan['operations'].append({'id': operation_key('payment', payment.exchange_id),
                'type': ('cash_receipt' if amount > 0 else 'cash_refund') if cash else 'manual',
                'date': payment.date.isoformat(), 'amount': money(abs(amount) if cash else amount),
                'debit': ('62.2' if amount < 0 else '50.1') if cash else debit,
                'credit': ('50.1' if amount < 0 else '62.2') if cash else '62.2',
                'contract': key, 'payer': item['payer'], 'payments': [item['id']],
                'status': 'requires_cash_analytics' if cash else 'draft'})
        if uncertain or contract.cost <= 0 or contract.profit <= 0:
            record['shipment_status'] = 'requires_review'
            issue('shipment_requires_review')
        elif crossed:
            record['shipment_date'] = crossed.isoformat()
            record['shipment_status'] = 'in_period' if crossed.year == year else 'outside_period'
    included = {r['id'] for r in plan['contracts']}
    for _, item in offsets:
        day = date.fromisoformat(item['date'])
        # Check the WHOLE source for competing candidates, not only selected sample.
        candidates = list(Payment.objects.filter(date=day, amount=abs(Decimal(item['amount'])),
            kind__in=CLIENT_KINDS, method__name__in=['Зачет', 'Зачёт'])
            .select_related('contract__customer', 'legacy_payer'))
        plus = [p for p in candidates if p.kind == 'customer']
        minus = [p for p in candidates if p.kind == 'customer_refund']
        if len(plus) != 1 or len(minus) != 1 or plus[0].contract_id == minus[0].contract_id:
            item['status'] = 'ambiguous_offset'
        elif str(plus[0].contract.exchange_id) not in included or str(minus[0].contract.exchange_id) not in included:
            item['status'] = 'offset_counterpart_not_selected'
        else:
            source, target = minus[0], plus[0]
            op_id = operation_key('offset', source.exchange_id, target.exchange_id)
            item['status'] = 'offset_proposed'
            if not any(o['id'] == op_id for o in plan['operations']):
                plan['operations'].append({'id': op_id, 'type': 'offset', 'date': day.isoformat(),
                    'amount': money(source.amount), 'debit': '62.2', 'credit': '62.2',
                    'debit_contract': str(source.contract.exchange_id), 'credit_contract': str(target.contract.exchange_id),
                    'debit_payer': {'id': str(source.payer.exchange_id), 'name': source.payer.name},
                    'credit_payer': {'id': str(target.payer.exchange_id), 'name': target.payer.name},
                    'payments': [str(source.exchange_id), str(target.exchange_id)],
                    'status': 'confirm_pair'})
        if item['status'] != 'offset_proposed':
            issues.append({'code': item['status'], 'contract': item['contract'], 'payment': item['id'], 'number': ''})
    if any(len(values) > 1 for values in seen_names.values()):
        issues.append({'code': 'duplicate_customer_names', 'contract': '', 'payment': '', 'number': ''})
    return plan


def package_bytes(plan):
    """Own review format, deliberately NOT labelled as stock SAMO import XML."""
    root = ET.Element('CRM_TEST_EXPORT', VERSION='1', YEAR=str(plan['year']), TEST_ONLY='1')
    for c in plan['contracts']:
        node = ET.SubElement(root, 'CONTRACT', ID=c['id'], NUMBER=c['number'], DATE=c['date'],
                             AMOUNT=c['amount'], COST=c['cost'], COMMISSION=c['commission'], CURRENCY='RUB',
                             VOUCHER_DATE=c['voucher_date'], SHIPMENT_DATE=c['shipment_date'] or '',
                             SHIPMENT_STATUS=c['shipment_status'])
        ET.SubElement(node, 'CUSTOMER', ID=c['customer']['id'], NAME=c['customer']['name'])
        ET.SubElement(node, 'OPERATOR', ID=c['operator']['id'], NAME=c['operator']['name'])
        ET.SubElement(node, 'ROW', CUSTOMER=c['customer']['id'], AMOUNT=c['amount'], COST=c['cost'])
        for payment in c['payments']:
            ET.SubElement(node, 'PAYMENT', ID=payment['id'], DATE=payment['date'],
                AMOUNT=payment['amount'], METHOD=payment['method'], STATUS=payment['status'],
                PAYER_ID=payment['payer']['id'], PAYER_NAME=payment['payer']['name'])
    operations = ET.SubElement(root, 'OPERATIONS')
    for operation in plan['operations']:
        node = ET.SubElement(operations, 'OPERATION', **{
            key.upper(): str(value) for key, value in operation.items()
            if not isinstance(value, (dict, list))})
        for side in ('payer', 'debit_payer', 'credit_payer'):
            if side in operation:
                ET.SubElement(node, side.upper(), ID=operation[side]['id'], NAME=operation[side]['name'])
        for key in operation['payments']:
            ET.SubElement(node, 'SOURCE_PAYMENT', ID=key)
    issues = ET.SubElement(root, 'ISSUES')
    for issue in plan['issues']:
        ET.SubElement(issues, 'ISSUE', **{key.upper(): value for key, value in issue.items()})
    xml = ET.tostring(root, encoding='windows-1251', xml_declaration=True)
    try:
        ET.fromstring(xml)
    except ET.ParseError as exc:
        raise ValueError('В выбранных записях есть недопустимые для XML символы. Исправьте их перед выгрузкой.') from exc
    output = io.BytesIO()
    with ZipFile(output, 'w', ZIP_DEFLATED) as archive:
        archive.writestr('plan.json', json.dumps(plan, ensure_ascii=False, indent=2).encode())
        archive.writestr('exchange.xml', xml)
        archive.writestr('contracts.csv', csv_bytes(
            ['Договор', 'Дата', 'Заказчик', 'ТО', 'Сумма', 'Себестоимость', 'Комиссия', 'Дата отгрузки', 'Проверка отгрузки'],
            [[c['number'], c['date'], c['customer']['name'], c['operator']['name'], Decimal(c['amount']), Decimal(c['cost']),
              Decimal(c['commission']), c['shipment_date'] or '', label(c['shipment_status'])] for c in plan['contracts']]))
        numbers = {c['id']: c['number'] for c in plan['contracts']}
        archive.writestr('operations.csv', csv_bytes(
            ['ID', 'Вид', 'Дата', 'Дебет', 'Кредит', 'Сумма', 'Договор / источник зачёта',
             'Заказчик / источник зачёта', 'Договор-получатель зачёта', 'Заказчик-получатель зачёта', 'Проверка'],
            [[o['id'], label(o['type']), o['date'], o['debit'], o['credit'], Decimal(o['amount']),
              numbers.get(o.get('contract', o.get('debit_contract')), ''),
              o.get('payer', o.get('debit_payer', {})).get('name', ''),
              numbers.get(o.get('credit_contract'), ''), o.get('credit_payer', {}).get('name', ''),
              label(o['status'])] for o in plan['operations']]))
        archive.writestr('payments.csv', csv_bytes(
            ['Договор', 'Дата', 'Плательщик', 'Способ оплаты', 'Сумма со знаком', 'Результат'],
            [[c['number'], p['date'], p['payer']['name'], p['method'], Decimal(p['amount']), label(p['status'])]
             for c in plan['contracts'] for p in c['payments']]))
        archive.writestr('issues.csv', csv_bytes(
            ['Договор', 'ID договора', 'ID платежа', 'Замечание'],
            [[i['number'], i['contract'], i['payment'], label(i['code'])] for i in plan['issues']]))
        archive.writestr('README.txt', ('ТЕСТОВЫЙ ПАКЕТ ДЛЯ СВЕРКИ, НЕ ГОТОВАЯ ЗАГРУЗКА В 1С.\n'
            'exchange.xml — собственный формат CRM, не XML загрузчика САМО.\n'
            'Приёмник 1С ещё разрабатывается. Не загружайте пакет штатной обработкой САМО.\n'
            'plan.json содержит связи, клиентские платежи и замечания. CSV — для проверки сумм.\n'
            'Одна строка заявки — заказчик. Паспортов, контактов, списка туристов в пакете нет.\n'
            'Операции — проект: зачёты требуют подтверждения пары, кассовые — проверки аналитик.\n'
            'Период платежей — выбранный год; порог отгрузки проверен по всей истории договора.\n'
            'Возвраты, зачёты, неизвестный способ оплаты и нулевая/отрицательная комиссия требуют проверки отгрузки.\n'
            'Существующие документы 1С не изменены. Тестировать только в отдельной копии.\n').encode('utf-8-sig'))
    return output.getvalue()
