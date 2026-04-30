@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo =============================================
echo FHD ��������׼�������ݿ����� + ����������
echo =============================================

call "%~dp0scripts\docker-postgres-for-fhd.cmd"
if errorlevel 1 (
    echo [WARN] Docker Postgres ����ʧ�ܣ����ֶ����� Postgres �����ԡ�
)

call "%~dp0scripts\fhd-set-database-url.cmd"

echo =============================================
echo [OK] DATABASE_URL �� PYTHONPATH �������ڵ�ǰ���ڡ�
echo      Ĭ�����ݿ��ַ: postgresql+psycopg://xcagi:***@127.0.0.1:5433/xcagi
echo      ˫��һ������: start-xcagi.bat
echo      ���: �˿� 5000 (FastAPI, app.fastapi_app:get_fastapi_app)
echo =============================================
