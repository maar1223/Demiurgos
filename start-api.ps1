$env:PYTHONPATH = "src\tools\demiurgos-suite\wiki;src\tools\demiurgos-suite"
Set-Location "<local-path>\Proyectos\Demiurgos"
python -c "import uvicorn; from api_server import app; uvicorn.run(app, host='127.0.0.1', port=8000, log_level='info')"
