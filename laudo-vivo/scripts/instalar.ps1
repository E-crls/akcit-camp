<#
Instalador do Laudo Vivo para Windows (PowerShell 5.1 ou 7). Um comando, na pasta laudo-vivo\:

  powershell -ExecutionPolicy Bypass -File scripts\instalar.ps1

Faz o mesmo que scripts/instalar.sh:
  1. ambiente: com micromamba, mamba ou conda no PATH (nessa ordem), cria ou atualiza o ambiente
     "laudo-vivo" a partir do environment.yml (conda-forge). Sem nenhum deles, cria .venv\ com Python 3.12
     (py -3.12 ou python) e instala o pyproject.toml do PyPI (extras geo, vision e voice e o grupo dev);
  2. voz: no ambiente conda, tenta `pip install faster-whisper` (só existe no PyPI; é opcional) e aplica o
     ajuste de OpenMP da docs/adr/002-ambiente.md (scripts\preparar_demo.py --ajustar-openmp);
  3. ativos: scripts\preparar_demo.py (vídeo e satélite da demo vêm do repositório; o detector YOLOX é
     baixado da release oficial; tudo com sha256 conferido);
  4. teste rápido: a demo da linha de comando com ferramentas reais e LLM gravado (19 passos, ~15 s) e a
     conferência do laudo selado de exemplo.
O comando do Python fica registrado em dados_locais\interpretador.

Opções: -Venv (força venv + pip), -Nome NOME (padrão laudo-vivo), -SemVoz, -SemTeste.
Requisitos, tempos e problemas comuns: docs\COMO_RODAR.md. Nada aqui exige GPU nem login em serviço algum.
#>
param(
  [switch]$Venv,
  [string]$Nome = "laudo-vivo",
  [switch]$SemVoz,
  [switch]$SemTeste
)
$ErrorActionPreference = "Stop"
$Raiz = Split-Path -Parent $PSScriptRoot
Set-Location $Raiz
$env:PYTHONPATH = Join-Path $Raiz "src"
$env:PYTHONUTF8 = "1"
$inicio = Get-Date
$script:PyCmd = @()

function Etapa([string]$texto) { Write-Host ""; Write-Host "== $texto ==" }
function Falhar([string]$texto) { Write-Host $texto -ForegroundColor Red; exit 1 }

# Executa um comando nativo (lista: programa e argumentos fixos) mais os argumentos dados; a saída vai para a
# tela e o código de saída fica em $LASTEXITCODE.
function Rodar([string[]]$cmd, [string[]]$argumentos) {
  $resto = @()
  if ($cmd.Length -gt 1) { $resto = $cmd[1..($cmd.Length - 1)] }
  & $cmd[0] @resto @argumentos | Out-Host
}
# O mesmo, devolvendo a saída padrão (linhas) em vez de mostrá-la.
function Capturar([string[]]$cmd, [string[]]$argumentos) {
  $resto = @()
  if ($cmd.Length -gt 1) { $resto = $cmd[1..($cmd.Length - 1)] }
  return (& $cmd[0] @resto @argumentos)
}

# --- 1. ambiente -----------------------------------------------------------------------------------------
$gerente = $null
if (-not $Venv) {
  foreach ($g in @("micromamba", "mamba", "conda")) {
    if (Get-Command $g -ErrorAction SilentlyContinue) { $gerente = $g; break }
  }
}

if ($gerente) {
  Etapa "1/4 ambiente conda-forge `"$Nome`" com $gerente (environment.yml)"
  if ($gerente -eq "conda") {
    $script:PyCmd = @("conda", "run", "--no-capture-output", "-n", $Nome, "python")
  }
  else { $script:PyCmd = @($gerente, "run", "-n", $Nome, "python") }
  # micromamba aceita o .yml em create/install; conda e mamba, em env create/env update (sem perguntar)
  $env:CONDA_ALWAYS_YES = "true"; $env:MAMBA_ALWAYS_YES = "true"
  $arqEnv = "environment.yml"
  $null = Capturar $script:PyCmd @("-c", "import sys")
  if ($LASTEXITCODE -eq 0) {
    Write-Host "o ambiente já existe: atualizando"
    if ($gerente -eq "micromamba") { Rodar @("micromamba") @("install", "-y", "-n", $Nome, "-f", $arqEnv) }
    else { Rodar @($gerente) @("env", "update", "-n", $Nome, "-f", $arqEnv) }
  } else {
    if ($gerente -eq "micromamba") { Rodar @("micromamba") @("create", "-y", "-n", $Nome, "-f", $arqEnv) }
    else { Rodar @($gerente) @("env", "create", "-n", $Nome, "-f", $arqEnv) }
  }
  if ($LASTEXITCODE -ne 0) { Falhar "não foi possível criar o ambiente (veja acima e docs\COMO_RODAR.md)" }
  if (-not $SemVoz) {
    Etapa "2/4 voz (opcional): faster-whisper do PyPI"
    Rodar $script:PyCmd @("-m", "pip", "install", "--retries", "1", "--timeout", "20", "faster-whisper>=1.1")
    if ($LASTEXITCODE -ne 0) {
      Write-Host "AVISO: faster-whisper não instalado (PyPI inacessível?). A demo em replay não depende dele;"
      Write-Host "       sem ele, a fala é digitada e os 5 testes de tests/unit/test_voz_asr.py falham."
    } else {
      Write-Host "voz: ok"
      # o ctranslate2 do PyPI e o shim de OpenMP do conda-forge (docs/adr/002-ambiente.md)
      Rodar $script:PyCmd @("scripts\preparar_demo.py", "--ajustar-openmp")
    }
  } else { Etapa "2/4 voz: pulada (-SemVoz)" }
} else {
  Etapa "1/4 ambiente: venv + pip (Python 3.12), sem conda/micromamba no PATH"
  $base = $null
  foreach ($c in @(@("py", "-3.12"), @("python3.12"), @("python"))) {
    if (-not (Get-Command $c[0] -ErrorAction SilentlyContinue)) { continue }
    $null = Capturar $c @("-c", "import sys; sys.exit(0 if sys.version_info[:2] == (3, 12) else 1)")
    if ($LASTEXITCODE -eq 0) { $base = $c; break }
  }
  if (-not $base) {
    Falhar "Python 3.12 não encontrado. Instale o Python 3.12 ou o micromamba (docs\COMO_RODAR.md)."
  }
  if (-not (Test-Path ".venv")) {
    Rodar $base @("-m", "venv", ".venv")
    if ($LASTEXITCODE -ne 0) { Falhar "não foi possível criar o .venv" }
  }
  $script:PyCmd = @((Join-Path $Raiz ".venv\Scripts\python.exe"))
  # um .venv criado por outra ferramenta pode vir sem o pip
  $null = Capturar $script:PyCmd @("-m", "pip", "--version")
  if ($LASTEXITCODE -ne 0) { Rodar $script:PyCmd @("-m", "ensurepip", "--upgrade") }
  Rodar $script:PyCmd @("-m", "pip", "install", "--upgrade", "pip>=25.1")
  if ($SemVoz) { $extras = "geo,vision" } else { $extras = "geo,vision,voice" }
  # O pyproject.toml só tem mínimos; os tetos abaixo são os do environment.yml: o OpenCV 5 muda a saída do
  # HoughLinesP usada na integridade da foto e o PyAV 19 quebra o faster-whisper 1.2.1.
  Rodar $script:PyCmd @("-m", "pip", "install", "-e", ".[$extras]", "opencv-python-headless<5", "av<19",
    "pillow<13")
  if ($LASTEXITCODE -ne 0) { Falhar "pip install falhou (veja acima)" }
  Rodar $script:PyCmd @("-m", "pip", "install", "--group", "dev")
  if ($LASTEXITCODE -ne 0) { Falhar "pip install --group dev falhou (precisa de pip >= 25.1)" }
  if ($SemVoz) { Etapa "2/4 voz: pulada (-SemVoz)" } else { Etapa "2/4 voz: incluída no extra voice" }
}
New-Item -ItemType Directory -Force "dados_locais" | Out-Null
# UTF-8 sem BOM e, no caso do venv, caminho relativo com "/" (o make e o bash leem este arquivo)
$arqInterp = Join-Path $Raiz "dados_locais\interpretador"
$registro = $script:PyCmd -join " "
if (-not $gerente) { $registro = ".venv/Scripts/python.exe" }
[System.IO.File]::WriteAllText($arqInterp, $registro + "`n")
Rodar $script:PyCmd @("-c", "import sys; print('Python', sys.version.split()[0], 'em', sys.executable)")

# --- 3. ativos da demo -----------------------------------------------------------------------------------
Etapa "3/4 ativos da demo (vídeo, satélite e detector YOLOX, com sha256)"
Rodar $script:PyCmd @("scripts\preparar_demo.py")
if ($LASTEXITCODE -ne 0) { Falhar "os ativos da demo não ficaram prontos (veja acima e docs\COMO_RODAR.md)" }

# --- 4. teste rápido -------------------------------------------------------------------------------------
if (-not $SemTeste) {
  Etapa "4/4 teste rápido: demo de 19 passos (ferramentas reais, LLM gravado) e laudo de exemplo"
  $log = Join-Path $Raiz "dados_locais\instalar_demo.log"
  $saida = Capturar $script:PyCmd @("scripts\demo_cli.py", "--sem-cor", "--ferramentas", "reais", "--llm",
    "replay", "--replay", "tests/unit/dados_agente/replay_demo_real_qwen35_4b.jsonl")
  $rc = $LASTEXITCODE
  [System.IO.File]::WriteAllLines($log, [string[]]$saida)
  $saida | Select-String -Pattern "Etapa final|tempo total" | ForEach-Object { Write-Host $_.Line }
  if ($rc -ne 0) { Falhar "a demo não chegou ao SELADO (log completo em $log; veja docs\COMO_RODAR.md)" }
  $saida = Capturar $script:PyCmd @("docs\exemplos\conferir_exemplo.py")
  $saida | Select-Object -Last 4 | ForEach-Object { Write-Host $_ }
} else { Etapa "4/4 teste rápido: pulado (-SemTeste)" }

# --- pronto ----------------------------------------------------------------------------------------------
$seg = [int]((Get-Date) - $inicio).TotalSeconds
Write-Host ""
Write-Host "Pronto em $seg s. Python registrado em dados_locais\interpretador: $($script:PyCmd -join ' ')"
if ($gerente) { Write-Host "Para usar o ambiente neste terminal: $gerente activate $Nome" }
else { Write-Host "Para usar o ambiente neste terminal: .venv\Scripts\Activate.ps1" }
Write-Host @"
Depois, na pasta laudo-vivo\: `$env:PYTHONPATH = "src"; `$env:PYTHONUTF8 = "1", e então
  python scripts/demo_cli.py --ferramentas reais --llm replay ``
      --replay tests/unit/dados_agente/replay_demo_real_qwen35_4b.jsonl          # demo da CLI, 19 passos
  python -m laudo.api --caso DEMO-0001 --ferramentas reais --perfil campo --llm replay --asr desligado
      # interface web em replay: http://127.0.0.1:8000 (Ctrl+C encerra)
  python -m pytest tests -q                                                     # testes
Com Git Bash e make: make replay, make demo-web e make avaliar. Detalhes em docs\COMO_RODAR.md.
"@
