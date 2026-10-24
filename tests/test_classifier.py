import pytest
from backend.core.classifier import DocumentClassifier
from backend.models.schemas import DocumentType


class TestDocumentClassifier:
    
    @pytest.fixture
    def classifier(self):
        return DocumentClassifier()
    
    def test_passport_classification(self, classifier):
        """Классификация паспорта"""
        text = """
        паспорт гражданина российской федерации
        фамилия иванов
        имя иван
        отчество иванович
        пол муж
        место рождения г москва
        дата рождения 01.01.1980
        серия 4509 номер 123456
        код подразделения 772-043
        дата выдачи 15.06.2015
        """
        
        doc_type, confidence, candidates = classifier.classify(text)
        assert doc_type == DocumentType.PASSPORT
        assert confidence >= 2.0
    
    def test_passport_with_mrz(self, classifier):
        """Паспорт с MRZ"""
        text = """
        паспорт
        4509 123456
        P<RUSIVANOV<<IVAN<<<<<<<<<<<<<<<<<<<<<<<
        7204043RUS8001015M2501016<<<<<<<<<<<<<<06
        """
        
        doc_type, confidence, candidates = classifier.classify(text)
        assert doc_type == DocumentType.PASSPORT
        assert confidence > 2.0
    
    def test_egrn_structural(self, classifier):
        """ЕГРН со структурными признаками"""
        text = """
        выписка из единого государственного реестра недвижимости
        об объекте недвижимости
        
        кадастровый номер 77:01:0001001:1234
        адрес объекта г москва ул ленина д 1 кв 10
        
        вид права собственность
        правообладатель иванов иван иванович
        доля в праве 1/1
        
        кадастровая стоимость 5000000.00 руб
        
        площадь 50.5 м2
        назначение жилое
        
        запись регистрации 77-77-01/001/2020-001
        дата регистрации 15.01.2020
        
        управление федеральной службы государственной регистрации
        кадастра и картографии по г москве
        """
        
        doc_type, confidence, candidates = classifier.classify(text)
        assert doc_type == DocumentType.EGRN
        assert confidence >= 2.0
    
    def test_dkp_vs_pdkp(self, classifier):
        """Различение ДКП и ПДКП"""
        # Обычный договор
        dkp_text = """
        договор купли-продажи недвижимого имущества
        продавец иванов иван иванович
        покупатель петров петр петрович
        предмет договора квартира
        """
        
        doc_type, _, _ = classifier.classify(dkp_text)
        assert doc_type == DocumentType.DKP
        
        # Предварительный договор
        pdkp_text = """
        предварительный договор купли-продажи недвижимого имущества
        продавец иванов иван иванович
        покупатель петров петр петрович
        стороны обязуются заключить основной договор
        """
        
        doc_type, _, _ = classifier.classify(pdkp_text)
        assert doc_type == DocumentType.PDKP
    
    def test_form_number_with_phrase(self, classifier):
        """Номер формы с обязательной фразой"""
        text = """
        платежное поручение
        форма по окпо 0401060
        плательщик ооо рога и копыта
        получатель оао газпром
        """
        
        doc_type, confidence, _ = classifier.classify(text)
        assert doc_type == DocumentType.PAYMENT_ORDER
        assert confidence >= 2.0
    
    def test_unknown_for_low_score(self, classifier):
        """Возврат unknown при низком score"""
        text = "неопределённый текст без явных признаков"
        
        doc_type, confidence, candidates = classifier.classify(text)
        assert doc_type == DocumentType.UNKNOWN
        assert len(candidates) > 0  # Должны быть кандидаты
    
    def test_unknown_for_low_margin(self, classifier):
        """Возврат unknown при недостаточном отрыве"""
        # Текст с признаками нескольких типов документов
        text = """
        справка выдана иванову
        договор номер 123
        """
        
        doc_type, confidence, candidates = classifier.classify(text)
        # Если отрыв недостаточен, должен вернуть unknown
        if len(candidates) >= 2:
            margin = candidates[0].score - candidates[1].score
            if margin < classifier.min_margin:
                assert doc_type == DocumentType.UNKNOWN
    
    def test_filename_hint_with_confirmation(self, classifier):
        """Подсказка из имени файла с подтверждением"""
        text = "паспорт российской федерации серия номер"
        
        doc_type, confidence, _ = classifier.classify(text, filename="passport_scan.pdf")
        assert doc_type == DocumentType.PASSPORT
        assert confidence > 2.0
    
    def test_no_single_word_classification(self, classifier):
        """Не должен классифицировать по одному слову"""
        text = "договор"
        
        doc_type, confidence, _ = classifier.classify(text)
        # Одно слово не должно давать уверенную классификацию
        assert doc_type == DocumentType.UNKNOWN or confidence < 2.0
    
    def test_passport_series_with_inner_space(self, classifier):
        """Серия паспорта с пробелом внутри: «Серия 45 00 № 123456»"""
        text = "российская федерация паспорт серия 45 00 номер 123456"
        
        doc_type, confidence, _ = classifier.classify(text)
        assert doc_type == DocumentType.PASSPORT
        assert confidence >= 3.0
    
    def test_passport_title_alone_not_enough(self, classifier):
        """Одного слова «паспорт» без номера недостаточно"""
        doc_type, _, _ = classifier.classify("паспорт")
        assert doc_type == DocumentType.UNKNOWN
    
    def test_cadastral_number_not_enough(self, classifier):
        """Кадастровый номер сам по себе недостаточен для ЕГРН"""
        text = "кадастровый номер 77:01:0001001:1234"
        
        doc_type, _, _ = classifier.classify(text)
        # Без других признаков не должен быть ЕГРН
        if doc_type == DocumentType.EGRN:
            # Если всё же ЕГРН, confidence должна быть низкой
            pytest.fail("ЕГРН не должен определяться только по кадастровому номеру")
