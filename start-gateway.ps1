Set-Location "<local-path>\Proyectos\Demiurgos"
$env:DEMIURGOS_ROOT = (Get-Location).Path
$env:HERMES_ENABLE_PROJECT_PLUGINS = "1"
& "C:\Users\Miguel Angel\AppData\Local\hermes\hermes-agent\venv\Scripts\hermes.exe" plugins enable demiurgos-idea-capture *> $null
if ($LASTEXITCODE -ne 0) { throw "Could not enable the Demiurgos Hermes project plugin." }
& "C:\Users\Miguel Angel\AppData\Local\hermes\hermes-agent\venv\Scripts\hermes.exe" gateway run -v
