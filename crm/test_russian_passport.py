from django.test import SimpleTestCase
from .passport_parser import parse_passport,mrz_digit


def domestic_mrz():
    # Artificial document, never a real person's passport.
    first='PNRUSIVANOV<<IVAN<IVANOVI3'.ljust(44,'<')
    number='451123456';birth='900201'
    extra='2'+'160405'+'123456'+'<'
    second=number+mrz_digit(number)+'RUS'+birth+mrz_digit(birth)+'M'+'<<<<<<<'+extra+mrz_digit(extra)
    second+=mrz_digit(second[:10]+second[13:20]+second[21:43])
    assert len(second)==44
    return first,second


class RussianPassportTests(SimpleTestCase):
    def test_russian_customer_fields_from_internal_passport(self):
        first,second=domestic_mrz()
        result=parse_passport(first+'\n'+second,'customer')
        self.assertEqual(result['surname'],'Иванов');self.assertEqual(result['given_name'],'Иван')
        self.assertEqual(result['patronymic'],'Иванович');self.assertEqual(result['passport_type'],'1')
        self.assertEqual(result['passport_number'],'4512123456')
        self.assertEqual(result['birthday'],'1990-02-01');self.assertEqual(result['passport_issued'],'2016-04-05')
        self.assertEqual(result['passport_code'],'123-456');self.assertNotIn('expires',result)
    def test_spacing_noise_in_nationality_and_cyrillic_gender(self):
        first,second=domestic_mrz()
        second=second[:10]+'81$'+second[13:20]+'М'+second[21:]
        first=first.replace('IVANOV<<','IVANOV <<').replace('IVAN<','IVAN <')
        result=parse_passport(first+'\n\n'+second,'customer')
        self.assertEqual(result['passport_number'],'4512123456');self.assertEqual(result['name'],'Иванов Иван Иванович')
    def test_checksum_failure_never_fills_guessed_number_or_issue_details(self):
        first,second=domestic_mrz()
        broken=second[:28]+'3'+second[29:]
        result=parse_passport(first+'\n'+broken,'customer')
        self.assertNotIn('passport_number',result);self.assertNotIn('passport_issued',result)
        self.assertNotIn('passport_code',result);self.assertEqual(result['birthday'],'1990-02-01')
    def test_clear_printed_name_before_label_corrects_mrz_ocr(self):
        first,second=domestic_mrz()
        first=first.replace('IVANOVI3','IVANOVIS')
        result=parse_passport('ИВАНОВИЧ\nОтчество\n'+first+'\n'+second,'customer')
        self.assertEqual(result['patronymic'],'Иванович')
    def test_russian_passport_for_tourist(self):
        first,second=domestic_mrz();result=parse_passport(first+'\n'+second,'tourist')
        self.assertEqual(result['passport_type'],'1');self.assertEqual(result['gender'],'male')
        self.assertEqual(result['issued'],'2016-04-05');self.assertNotIn('patronymic',result)
