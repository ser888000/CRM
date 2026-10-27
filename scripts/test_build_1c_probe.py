"""Tests of composition only; these do not compile or execute 1C."""
from pathlib import Path
import re
import tempfile
import unittest

from build_1c_probe import unified_source


class UnifiedCompositionTests(unittest.TestCase):
    def test_real_modules_have_unique_functions_and_resolved_stage_calls(self):
        directory = Path(__file__).resolve().parents[1] / 'integrations' / '1c77'
        source = unified_source(directory)
        names = re.findall(r'^(?:Функция|Процедура) (\w+)\(', source, re.M)
        self.assertEqual(len(names), len(set(names)))
        for name in ('crmUUID', 'crmError', 'crmExisting', 'ПриОткрытии', 'crmEnsureApplicationServices'):
            self.assertEqual(names.count(name), 1)
        calls = set(re.findall(r'\b([avsp]_crm\w+)\(', source))
        self.assertTrue(calls.issubset(set(names)), calls - set(names))
        for entry in ('a_crmImport', 'v_crmImportVoucher', 's_crmImportShipment', 'p_crmImportPayment'):
            self.assertIn(entry, names)
        for literal in ('[CRM_OP:', '[CRM_PAYMENT:', 'CRM_TEST_EXPORT', 'Комиссионные путевки'):
            self.assertIn(literal, source)
        source.encode('cp1251')

    def test_1c77_local_procedures_are_defined_before_their_calls(self):
        directory = Path(__file__).resolve().parents[1] / 'integrations' / '1c77'
        source = unified_source(directory)
        definitions = list(re.finditer(r'^(?:Функция|Процедура) (\w+)\(', source, re.M))
        positions = {match[1]: match.start() for match in definitions}
        # 7.7 resolves calls in declaration order; name existence alone is insufficient.
        clean = re.sub(r'"(?:""|[^"\n])*"|//[^\n]*', lambda match: ' ' * len(match[0]), source)
        for index, definition in enumerate(definitions):
            end = definitions[index + 1].start() if index + 1 < len(definitions) else len(source)
            body = clean[definition.end():end]
            for call in re.finditer(r'\b(\w+)\s*\(', body):
                if call[1] in positions:
                    self.assertLessEqual(positions[call[1]], definition.start(),
                                         f'{definition[1]} calls {call[1]} before declaration')
        self.assertLess(positions['crmBatchApplications'], positions['crmUnified'])

    def test_composition_preserves_strings_comments_and_distinct_helpers(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            (directory / 'unified.1c').write_text('Перем crmStage;\nПроцедура crmUnified()\nКонецПроцедуры\n')
            (directory / 'application_services.1c').write_text('// Shared services\n')
            shared = '\n'.join('Функция ' + name + '()\nВозврат 1;\nКонецФункции'
                               for name in ('crmUUID', 'crmError', 'crmExisting'))
            for module in ('application', 'voucher', 'shipment', 'payment'):
                (directory / (module + '.1c')).write_text(shared + '\n' +
                    'Функция crmStop()\n// crmStop stays in comments\n' +
                    'Сообщить("crmStop and ""crmStop""");\nВозврат crmStop();\nКонецФункции\n')
            source = unified_source(directory)
            self.assertEqual(source.count('Сообщить("crmStop and ""crmStop""");'), 4)
            self.assertEqual(source.count('// crmStop stays in comments'), 4)
            for prefix in ('a_', 'v_', 's_', 'p_'):
                self.assertIn('Возврат ' + prefix + 'crmStop();', source)
            path = directory / 'payment.1c'
            path.write_text(path.read_text().replace('Возврат 1;', 'Возврат 2;', 1))
            with self.assertRaisesRegex(ValueError, 'Shared helper differs'):
                unified_source(directory)


if __name__ == '__main__':
    unittest.main()
