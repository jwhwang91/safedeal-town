# ============================================================
#  SafeDeal Town - Windows 실행 스크립트
#  PowerShell 에서:   .\start.ps1
# ============================================================

Write-Host ""
Write-Host "  SafeDeal Town 을 시작합니다..." -ForegroundColor Cyan
Write-Host ""

# .env 가 없으면 예시 파일을 복사해준다
if (-not (Test-Path ".env")) {
    Write-Host "  .env 파일이 없어 .env.example 을 복사합니다." -ForegroundColor Yellow
    Copy-Item ".env.example" ".env"
    Write-Host "  -> 진짜 GPT API 를 쓰려면 .env 를 열어 OPENAI_API_KEY 를 채우고 AI_MODE=openai 로 바꾸세요."
    Write-Host ""
}

# 패키지 설치 여부 확인
python -c "import fastapi" 2>$null
if ($LASTEXITCODE -ne 0) {
    Write-Host "  필요한 패키지를 설치합니다 (pip install -r requirements.txt)..." -ForegroundColor Yellow
    pip install -r requirements.txt
    Write-Host ""
}

# 서버 실행
python run.py
