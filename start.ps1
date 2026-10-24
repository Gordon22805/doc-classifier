# Запуск сервиса
# Использование:  .\start.ps1
$ErrorActionPreference = "Stop"
$env:PYTHONIOENCODING = "utf-8"

if (-not (Test-Path ".env")) {
    Copy-Item ".env.example" ".env"
    Write-Host "Создан .env из .env.example" -ForegroundColor Yellow
}

# Проверяем, задан ли ключ OCR
$key = (Select-String -Path ".env" -Pattern '^OPENAI_API_KEY=(.+)$' -ErrorAction SilentlyContinue)
$hasKey = $key -and $key.Matches.Groups[1].Value.Trim()

$model = (Select-String -Path ".env" -Pattern '^VISION_MODEL=(.+)$' -ErrorAction SilentlyContinue)
$modelName = if ($model) { $model.Matches.Groups[1].Value.Trim() } else { "не задана" }

if ($hasKey) {
    Write-Host "OCR настроен, модель: $modelName" -ForegroundColor Green
} else {
    Write-Host "OPENAI_API_KEY не задан." -ForegroundColor Yellow
    Write-Host "Сервис запустится, но распознавать сканы не сможет:" -ForegroundColor Yellow
    Write-Host "  - PDF с текстовым слоем и DOCX будут обработаны;" -ForegroundColor Yellow
    Write-Host "  - сканы и изображения получат ошибку OCR." -ForegroundColor Yellow
    Write-Host ""
    Write-Host "Ключ OpenRouter (бесплатно): https://openrouter.ai/keys" -ForegroundColor Cyan
    Write-Host "Вставьте его в .env в строку OPENAI_API_KEY= и перезапустите." -ForegroundColor Cyan
    Write-Host ""
}

Write-Host "Откройте http://127.0.0.1:8000/" -ForegroundColor Green
Write-Host ""

py -m uvicorn backend.main:app --host 127.0.0.1 --port 8000
