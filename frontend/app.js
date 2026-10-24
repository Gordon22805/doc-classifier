const API_BASE = '/api';

let selectedFiles = [];
let currentJobId = null;
let currentPageData = null;

// Типы документов на русском
const DOC_TYPES = {
    'passport': 'Паспорт',
    'egrn': 'ЕГРН',
    'dkp': 'Договор купли-продажи',
    'pdkp': 'Предварительный ДКП',
    'ddu': 'Договор долевого участия',
    'zags': 'Документ ЗАГС',
    'inheritance': 'Документ о наследстве',
    'ezd': 'ЕЖД',
    'ndfl': 'НДФЛ',
    'sfr': 'СФР',
    'payment_order': 'Платёжное поручение',
    'accounting': 'Бухгалтерская отчётность',
    'reference': 'Справка',
    'unknown': 'Не распознан'
};

// Инициализация
document.addEventListener('DOMContentLoaded', () => {
    setupUploadZone();
    setupModal();
    
    const uploadBtn = document.getElementById('uploadBtn');
    uploadBtn.addEventListener('click', startProcessing);
});

// Зона загрузки
function setupUploadZone() {
    const uploadZone = document.getElementById('uploadZone');
    const fileInput = document.getElementById('fileInput');
    
    uploadZone.addEventListener('click', () => fileInput.click());
    
    fileInput.addEventListener('change', (e) => {
        handleFiles(e.target.files);
    });
    
    uploadZone.addEventListener('dragover', (e) => {
        e.preventDefault();
        uploadZone.classList.add('drag-over');
    });
    
    uploadZone.addEventListener('dragleave', () => {
        uploadZone.classList.remove('drag-over');
    });
    
    uploadZone.addEventListener('drop', (e) => {
        e.preventDefault();
        uploadZone.classList.remove('drag-over');
        handleFiles(e.dataTransfer.files);
    });
}

function handleFiles(files) {
    selectedFiles = Array.from(files);
    displayFileList();
    document.getElementById('uploadBtn').disabled = selectedFiles.length === 0;
}

function displayFileList() {
    const fileList = document.getElementById('fileList');
    
    if (selectedFiles.length === 0) {
        fileList.innerHTML = '';
        return;
    }
    
    fileList.innerHTML = selectedFiles.map((file, index) => `
        <div class="file-item">
            <span class="file-name">${file.name}</span>
            <span class="file-size">${formatFileSize(file.size)}</span>
            <button class="file-remove" onclick="removeFile(${index})">&times;</button>
        </div>
    `).join('');
}

function removeFile(index) {
    selectedFiles.splice(index, 1);
    displayFileList();
    document.getElementById('uploadBtn').disabled = selectedFiles.length === 0;
}

function formatFileSize(bytes) {
    if (bytes < 1024) return bytes + ' Б';
    if (bytes < 1024 * 1024) return (bytes / 1024).toFixed(1) + ' КБ';
    return (bytes / (1024 * 1024)).toFixed(1) + ' МБ';
}

// Обработка
async function startProcessing() {
    if (selectedFiles.length === 0) return;
    
    const formData = new FormData();
    selectedFiles.forEach(file => {
        formData.append('files', file);
    });
    
    try {
        document.getElementById('uploadBtn').disabled = true;
        showStatus();
        
        const response = await fetch(`${API_BASE}/upload`, {
            method: 'POST',
            body: formData
        });
        
        if (!response.ok) {
            throw new Error('Ошибка загрузки файлов');
        }
        
        const job = await response.json();
        currentJobId = job.job_id;
        
        pollJobStatus();
    } catch (error) {
        alert('Ошибка: ' + error.message);
        document.getElementById('uploadBtn').disabled = false;
    }
}

function showStatus() {
    document.getElementById('statusSection').style.display = 'block';
    document.getElementById('resultsSection').style.display = 'none';
}

function showResults() {
    document.getElementById('statusSection').style.display = 'none';
    document.getElementById('resultsSection').style.display = 'block';
}

async function pollJobStatus() {
    const pollInterval = setInterval(async () => {
        try {
            const response = await fetch(`${API_BASE}/status/${currentJobId}`);
            const job = await response.json();
            
            updateStatus(job);
            
            if (job.status === 'success' || job.status === 'partial_error' || job.status === 'error') {
                clearInterval(pollInterval);
                if (job.status !== 'error') {
                    displayResults(job);
                }
            }
        } catch (error) {
            console.error('Ошибка опроса статуса:', error);
        }
    }, 2000);
}

function updateStatus(job) {
    const statusBadge = document.getElementById('statusBadge');
    const statusInfo = document.getElementById('statusInfo');
    const progressFill = document.getElementById('progressFill');
    
    const statusText = {
        'pending': 'Ожидание',
        'processing': 'Обработка...',
        'success': 'Завершено',
        'partial_error': 'Завершено с ошибками',
        'error': 'Ошибка'
    };
    
    statusBadge.textContent = statusText[job.status] || job.status;
    
    if (job.total_pages > 0) {
        const progress = (job.processed_pages / job.total_pages) * 100;
        progressFill.style.width = progress + '%';
        statusInfo.textContent = `Обработано ${job.processed_pages} из ${job.total_pages} страниц`;
    } else {
        statusInfo.textContent = 'Подготовка...';
    }
}

function displayResults(job) {
    showResults();
    
    // Статистика
    const totalPages = job.pages.length;
    const recognizedPages = job.pages.filter(p => p.doc_type !== 'unknown').length;
    const unknownPages = totalPages - recognizedPages;
    
    document.getElementById('totalPages').textContent = totalPages;
    document.getElementById('recognizedPages').textContent = recognizedPages;
    document.getElementById('unknownPages').textContent = unknownPages;
    
    // Фильтры
    populateFilters(job.pages);
    
    // Страницы
    displayPages(job.pages);
    
    // Кнопка скачивания
    const downloadBtn = document.getElementById('downloadBtn');
    downloadBtn.onclick = () => downloadResults();
}

function populateFilters(pages) {
    const typeFilter = document.getElementById('typeFilter');
    const types = [...new Set(pages.map(p => p.doc_type))];
    
    typeFilter.innerHTML = '<option value="">Все типы</option>' +
        types.map(type => `<option value="${type}">${DOC_TYPES[type] || type}</option>`).join('');
    
    typeFilter.addEventListener('change', () => filterPages(pages));
    document.getElementById('statusFilter').addEventListener('change', () => filterPages(pages));
}

function filterPages(pages) {
    const typeFilter = document.getElementById('typeFilter').value;
    const statusFilter = document.getElementById('statusFilter').value;
    
    let filtered = pages;
    
    if (typeFilter) {
        filtered = filtered.filter(p => p.doc_type === typeFilter);
    }
    
    if (statusFilter) {
        filtered = filtered.filter(p => p.status === statusFilter);
    }
    
    displayPages(filtered);
}

function displayPages(pages) {
    const grid = document.getElementById('pagesGrid');
    
    grid.innerHTML = pages.map(page => {
        const docType = page.manual_correction ? page.corrected_type : page.doc_type;
        const pageError = page.diagnostics && page.diagnostics.error;
        const errorBlock = pageError
            ? `<div class="page-error">${escapeHtml(pageError)}</div>`
            : '';
        return `
            <div class="page-card${pageError ? ' page-card-error' : ''}" onclick="openPageModal('${page.page_id}')">
                <img class="page-preview" src="${API_BASE}/image/${currentJobId}/${page.page_id}" alt="Страница ${page.page_number}">
                <div class="page-info">
                    <div class="page-title">${page.source_file} - стр. ${page.page_number}</div>
                    <div class="page-type">${DOC_TYPES[docType] || docType}</div>
                    <div class="page-meta">Уверенность: ${page.confidence.toFixed(2)}</div>
                    <div class="page-meta">Источник: ${page.text_source}</div>
                    ${errorBlock}
                </div>
            </div>
        `;
    }).join('');
}

function escapeHtml(text) {
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
}

async function downloadResults() {
    window.location.href = `${API_BASE}/download/${currentJobId}`;
}

// Модальное окно
function setupModal() {
    const modal = document.getElementById('pageModal');
    const closeBtn = document.getElementById('modalClose');
    const cancelBtn = document.getElementById('modalCancelBtn');
    const saveBtn = document.getElementById('modalSaveBtn');
    
    closeBtn.addEventListener('click', closeModal);
    cancelBtn.addEventListener('click', closeModal);
    saveBtn.addEventListener('click', savePage);
    
    modal.addEventListener('click', (e) => {
        if (e.target === modal) closeModal();
    });
    
    // Заполняем селект типов
    const typeSelect = document.getElementById('modalTypeSelect');
    typeSelect.innerHTML = Object.entries(DOC_TYPES).map(([key, value]) => 
        `<option value="${key}">${value}</option>`
    ).join('');
}

async function openPageModal(pageId) {
    const response = await fetch(`${API_BASE}/status/${currentJobId}`);
    const job = await response.json();
    
    const page = job.pages.find(p => p.page_id === pageId);
    if (!page) return;
    
    currentPageData = page;
    
    const modal = document.getElementById('pageModal');
    document.getElementById('modalTitle').textContent = `${page.source_file} - страница ${page.page_number}`;
    document.getElementById('modalImage').src = `${API_BASE}/image/${currentJobId}/${page.page_id}`;
    document.getElementById('modalSource').textContent = page.source_file;
    document.getElementById('modalConfidence').textContent = page.confidence.toFixed(2);
    document.getElementById('modalTextSource').textContent = page.text_source;
    
    const docType = page.manual_correction ? page.corrected_type : page.doc_type;
    document.getElementById('modalTypeSelect').value = docType;
    
    modal.classList.add('active');
}

function closeModal() {
    document.getElementById('pageModal').classList.remove('active');
    currentPageData = null;
}

async function savePage() {
    if (!currentPageData) return;
    
    const newType = document.getElementById('modalTypeSelect').value;
    
    try {
        const response = await fetch(`${API_BASE}/correct/${currentJobId}/${currentPageData.page_id}?doc_type=${newType}`, {
            method: 'POST'
        });
        
        if (!response.ok) {
            throw new Error('Ошибка сохранения');
        }
        
        // Обновляем данные
        currentPageData.manual_correction = true;
        currentPageData.corrected_type = newType;
        
        // Перестраиваем результат
        await fetch(`${API_BASE}/rebuild/${currentJobId}`, { method: 'POST' });
        
        // Обновляем отображение
        const statusResponse = await fetch(`${API_BASE}/status/${currentJobId}`);
        const job = await statusResponse.json();
        displayResults(job);
        
        closeModal();
    } catch (error) {
        alert('Ошибка: ' + error.message);
    }
}
