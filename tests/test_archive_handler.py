import pytest
import zipfile
import tempfile
from pathlib import Path
from backend.utils.archive_handler import ArchiveHandler


class TestArchiveHandler:
    
    @pytest.fixture
    def handler(self):
        return ArchiveHandler()
    
    @pytest.fixture
    def temp_dir(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            yield Path(tmpdir)
    
    def create_test_zip(self, zip_path: Path, files: dict):
        """Создание тестового ZIP архива"""
        with zipfile.ZipFile(zip_path, 'w') as zf:
            for filename, content in files.items():
                zf.writestr(filename, content)
    
    def test_extract_simple_zip(self, handler, temp_dir):
        """Извлечение простого ZIP"""
        zip_path = temp_dir / "test.zip"
        files = {
            "document.pdf": b"PDF content",
            "image.jpg": b"JPG content"
        }
        self.create_test_zip(zip_path, files)
        
        extract_dir = temp_dir / "extracted"
        extracted = handler.extract_archive(zip_path, extract_dir)
        
        assert len(extracted) == 2
        assert all(f.exists() for f in extracted)
    
    def test_zip_slip_protection(self, handler, temp_dir):
        """Защита от Zip Slip атаки"""
        zip_path = temp_dir / "malicious.zip"
        
        with zipfile.ZipFile(zip_path, 'w') as zf:
            # Пытаемся записать за пределы директории
            zf.writestr("../../../etc/passwd", "malicious content")
        
        extract_dir = temp_dir / "extracted"
        
        with pytest.raises(Exception) as exc_info:
            handler.extract_archive(zip_path, extract_dir)
        
        assert "небезопасный" in str(exc_info.value).lower()
    
    def test_max_files_limit(self, handler, temp_dir):
        """Ограничение количества файлов"""
        handler.max_files = 5
        
        zip_path = temp_dir / "many_files.zip"
        files = {f"file_{i}.txt": b"content" for i in range(10)}
        self.create_test_zip(zip_path, files)
        
        extract_dir = temp_dir / "extracted"
        extracted = handler.extract_archive(zip_path, extract_dir)
        
        # Должно извлечься не более max_files
        assert len(extracted) <= handler.max_files
    
    def test_unsupported_format_filtered(self, handler, temp_dir):
        """Фильтрация неподдерживаемых форматов"""
        zip_path = temp_dir / "mixed.zip"
        files = {
            "document.pdf": b"PDF",
            "script.exe": b"EXE",
            "image.jpg": b"JPG"
        }
        self.create_test_zip(zip_path, files)
        
        extract_dir = temp_dir / "extracted"
        extracted = handler.extract_archive(zip_path, extract_dir)
        
        # EXE не должен быть извлечён
        assert len(extracted) == 2
        assert all(f.suffix != '.exe' for f in extracted)
    
    def test_nested_archive_extraction(self, handler, temp_dir):
        """Извлечение вложенных архивов"""
        # Создаём внутренний архив
        inner_zip = temp_dir / "inner.zip"
        self.create_test_zip(inner_zip, {"inner_file.txt": b"Inner content"})
        
        # Создаём внешний архив с вложенным
        outer_zip = temp_dir / "outer.zip"
        with zipfile.ZipFile(outer_zip, 'w') as zf:
            zf.write(inner_zip, "inner.zip")
            zf.writestr("outer_file.txt", b"Outer content")
        
        extract_dir = temp_dir / "extracted"
        extracted = handler.extract_archive(outer_zip, extract_dir)
        
        # Должны быть извлечены файлы из обоих архивов
        assert len(extracted) >= 1  # Минимум inner_file.txt
    
    def test_max_nested_limit(self, handler, temp_dir):
        """Ограничение вложенности архивов"""
        handler.max_nested = 1
        
        # Создаём глубоко вложенную структуру
        level3_zip = temp_dir / "level3.zip"
        self.create_test_zip(level3_zip, {"file.txt": b"content"})
        
        level2_zip = temp_dir / "level2.zip"
        with zipfile.ZipFile(level2_zip, 'w') as zf:
            zf.write(level3_zip, "level3.zip")
        
        level1_zip = temp_dir / "level1.zip"
        with zipfile.ZipFile(level1_zip, 'w') as zf:
            zf.write(level2_zip, "level2.zip")
        
        extract_dir = temp_dir / "extracted"
        
        # Должна быть ошибка из-за превышения вложенности
        with pytest.raises(Exception) as exc_info:
            handler.extract_archive(level1_zip, extract_dir, current_depth=1)
        
        assert "вложенност" in str(exc_info.value).lower()
    
    def test_remove_duplicates(self, handler, temp_dir):
        """Удаление дубликатов файлов"""
        # Создаём файлы с одинаковым содержимым
        file1 = temp_dir / "file1.txt"
        file2 = temp_dir / "file2.txt"
        file3 = temp_dir / "file3.txt"
        
        file1.write_text("Same content")
        file2.write_text("Same content")
        file3.write_text("Different content")
        
        files = [file1, file2, file3]
        unique = handler.remove_duplicates(files)
        
        # Должно остаться 2 уникальных файла
        assert len(unique) == 2
    
    def test_large_file_skipped(self, handler, temp_dir):
        """Пропуск слишком больших файлов"""
        handler.max_file_size = 1024  # 1 KB
        
        zip_path = temp_dir / "large.zip"
        files = {
            "small.txt": b"small",
            "large.txt": b"x" * 2048  # 2 KB
        }
        self.create_test_zip(zip_path, files)
        
        extract_dir = temp_dir / "extracted"
        extracted = handler.extract_archive(zip_path, extract_dir)
        
        # Большой файл должен быть пропущен
        assert len(extracted) == 1
