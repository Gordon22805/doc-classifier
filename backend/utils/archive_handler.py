import os
import zipfile
import logging
from pathlib import Path
from typing import List, Set
import hashlib

from backend.config import settings

logger = logging.getLogger(__name__)


class ArchiveHandler:
    """Безопасная обработка архивов ZIP и 7Z"""
    
    def __init__(self):
        self.max_files = settings.max_archive_files
        self.max_file_size = settings.max_file_size_mb * 1024 * 1024
        self.max_total_size = settings.max_total_unpack_size_mb * 1024 * 1024
        self.max_nested = settings.max_nested_archives
        self.supported_extensions = {
            '.pdf', '.jpg', '.jpeg', '.png', '.heic',
            '.docx', '.zip', '.7z', '.txt'
        }
    
    def extract_archive(
        self,
        archive_path: Path,
        extract_to: Path,
        current_depth: int = 0
    ) -> List[Path]:
        """
        Безопасное извлечение архива
        
        Args:
            archive_path: Путь к архиву
            extract_to: Директория для распаковки
            current_depth: Текущий уровень вложенности
        
        Returns:
            Список путей к извлечённым файлам
        
        Raises:
            Exception: При превышении лимитов или небезопасных путях
        """
        if current_depth >= self.max_nested:
            raise Exception(f"Превышен лимит вложенности архивов: {self.max_nested}")
        
        extract_to.mkdir(parents=True, exist_ok=True)
        
        suffix = archive_path.suffix.lower()
        
        if suffix == '.zip':
            return self._extract_zip(archive_path, extract_to, current_depth)
        elif suffix == '.7z':
            return self._extract_7z(archive_path, extract_to, current_depth)
        else:
            raise Exception(f"Неподдерживаемый формат архива: {suffix}")
    
    def _extract_zip(
        self,
        zip_path: Path,
        extract_to: Path,
        current_depth: int
    ) -> List[Path]:
        """Извлечение ZIP архива"""
        extracted_files = []
        total_size = 0
        file_count = 0
        seen_hashes: Set[str] = set()
        
        try:
            with zipfile.ZipFile(zip_path, 'r') as zf:
                # Проверка на zip bomb
                uncompressed_size = sum(info.file_size for info in zf.infolist())
                if uncompressed_size > self.max_total_size:
                    raise Exception(
                        f"Архив слишком большой после распаковки: "
                        f"{uncompressed_size / 1024 / 1024:.1f} MB"
                    )
                
                for info in zf.infolist():
                    if info.is_dir():
                        continue
                    
                    # Проверка лимита файлов
                    file_count += 1
                    if file_count > self.max_files:
                        logger.warning(f"Превышен лимит файлов в архиве: {self.max_files}")
                        break
                    
                    # Проверка на Zip Slip
                    member_path = self._safe_path(extract_to, info.filename)
                    
                    # Проверка расширения
                    if not self._is_supported(member_path):
                        continue
                    
                    # Извлекаем файл
                    member_path.parent.mkdir(parents=True, exist_ok=True)
                    
                    with zf.open(info) as source:
                        content = source.read()
                        
                        # Проверка размера после извлечения
                        actual_size = len(content)
                        if actual_size > self.max_file_size:
                            logger.warning(
                                f"Файл {info.filename} слишком большой: "
                                f"{actual_size / 1024 / 1024:.1f} MB, пропущен"
                            )
                            continue
                        
                        # Проверка на дубликаты по содержимому
                        content_hash = hashlib.sha256(content).hexdigest()
                        if content_hash in seen_hashes:
                            logger.info(f"Дубликат файла {info.filename}, пропущен")
                            continue
                        seen_hashes.add(content_hash)
                        
                        # Записываем файл
                        with open(member_path, 'wb') as target:
                            target.write(content)
                    
                    total_size += actual_size
                    
                    # Если это вложенный архив, распаковываем рекурсивно
                    if member_path.suffix.lower() in {'.zip', '.7z'}:
                        try:
                            nested_files = self.extract_archive(
                                member_path,
                                member_path.parent / member_path.stem,
                                current_depth + 1
                            )
                            extracted_files.extend(nested_files)
                        except Exception as e:
                            logger.error(f"Ошибка распаковки вложенного архива {member_path}: {e}")
                    else:
                        extracted_files.append(member_path)
        
        except zipfile.BadZipFile as e:
            raise Exception(f"Повреждённый ZIP архив: {str(e)}")
        
        logger.info(
            f"Извлечено {len(extracted_files)} файлов из {zip_path.name}, "
            f"размер: {total_size / 1024 / 1024:.1f} MB"
        )
        
        return extracted_files
    
    def _extract_7z(
        self,
        archive_path: Path,
        extract_to: Path,
        current_depth: int
    ) -> List[Path]:
        """Извлечение 7Z архива"""
        try:
            import py7zr
        except ImportError:
            raise Exception(
                "Для обработки 7Z архивов требуется установить библиотеку py7zr: "
                "pip install py7zr"
            )
        
        extracted_files = []
        total_size = 0
        file_count = 0
        seen_hashes: Set[str] = set()
        
        try:
            with py7zr.SevenZipFile(archive_path, 'r') as archive:
                all_files = archive.getnames()
                
                for filename in all_files:
                    file_count += 1
                    if file_count > self.max_files:
                        logger.warning(f"Превышен лимит файлов в архиве: {self.max_files}")
                        break
                    
                    # Проверка на безопасный путь
                    member_path = self._safe_path(extract_to, filename)
                    
                    # Проверка расширения
                    if not self._is_supported(member_path):
                        continue
                    
                    # Извлекаем
                    member_path.parent.mkdir(parents=True, exist_ok=True)
                    archive.extract(targets=[filename], path=str(extract_to))
                    
                    if member_path.exists():
                        file_size = member_path.stat().st_size
                        
                        if file_size > self.max_file_size:
                            member_path.unlink()
                            logger.warning(f"Файл {filename} слишком большой, удалён")
                            continue
                        
                        # Проверка на дубликаты
                        with open(member_path, 'rb') as f:
                            content_hash = hashlib.sha256(f.read()).hexdigest()
                            if content_hash in seen_hashes:
                                member_path.unlink()
                                logger.info(f"Дубликат файла {filename}, удалён")
                                continue
                            seen_hashes.add(content_hash)
                        
                        total_size += file_size
                        
                        # Рекурсивная распаковка
                        if member_path.suffix.lower() in {'.zip', '.7z'}:
                            try:
                                nested_files = self.extract_archive(
                                    member_path,
                                    member_path.parent / member_path.stem,
                                    current_depth + 1
                                )
                                extracted_files.extend(nested_files)
                            except Exception as e:
                                logger.error(f"Ошибка распаковки вложенного архива: {e}")
                        else:
                            extracted_files.append(member_path)
        
        except Exception as e:
            raise Exception(f"Ошибка извлечения 7Z архива: {str(e)}")
        
        logger.info(f"Извлечено {len(extracted_files)} файлов из {archive_path.name}")
        
        return extracted_files
    
    def _safe_path(self, base_dir: Path, member_name: str) -> Path:
        """
        Проверка на Zip Slip атаку
        
        Гарантирует, что извлечённый файл остаётся внутри base_dir
        """
        member_path = (base_dir / member_name).resolve()
        base_resolved = base_dir.resolve()
        
        if not str(member_path).startswith(str(base_resolved)):
            raise Exception(
                f"Небезопасный путь в архиве: {member_name} "
                f"пытается записать за пределы рабочей директории"
            )
        
        return member_path
    
    def _is_supported(self, path: Path) -> bool:
        """Проверка поддерживаемого расширения"""
        return path.suffix.lower() in self.supported_extensions
    
    def remove_duplicates(self, files: List[Path]) -> List[Path]:
        """
        Удаление дубликатов файлов по содержимому
        
        Не удаляет разные страницы с одинаковым содержимым
        без дополнительных правил
        """
        seen_hashes: Set[str] = set()
        unique_files = []
        
        for file_path in files:
            try:
                with open(file_path, 'rb') as f:
                    content_hash = hashlib.sha256(f.read()).hexdigest()
                    
                    if content_hash not in seen_hashes:
                        seen_hashes.add(content_hash)
                        unique_files.append(file_path)
                    else:
                        logger.info(f"Дубликат файла {file_path.name}, пропущен")
            except Exception as e:
                logger.error(f"Ошибка проверки файла {file_path}: {e}")
        
        return unique_files
