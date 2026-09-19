# Skill Office Agent demo (PowerShell)
# Usage (from repo root):
#   powershell -File examples/run_demo.ps1
# Or:
#   cd examples; .\run_demo.ps1

$py = if ($env:MIMO_PYTHON) { $env:MIMO_PYTHON } else { "python" }
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root
Write-Host "Project root: $root" -ForegroundColor DarkGray

Write-Host "=== 1) List skills ===" -ForegroundColor Cyan
& $py run_cli.py skills

Write-Host "`n=== 2) Route only ===" -ForegroundColor Cyan
& $py run_cli.py route "找到销售表并统计各区域销售额，生成报告并起草同步邮件"

Write-Host "`n=== 3) Multi-skill serial run (hybrid) ===" -ForegroundColor Cyan
& $py run_cli.py run "找到销售表并统计各区域销售额，生成报告并起草同步邮件" `
  --args-file "data/workspace/demo_args.json" --mode hybrid

Write-Host "`n=== 4) Web search → knowledge-base fallback ===" -ForegroundColor Cyan
& $py run_cli.py run "搜索一下远程办公协作要点" --skills "web-search"

Write-Host "`n=== 5) Function Calling tool ===" -ForegroundColor Cyan
$toolArgs = Join-Path $root "data/workspace/tool_args.json"
& $py run_cli.py call-tool describe_table --args-file $toolArgs

Write-Host "`nDone. Outputs: data/workspace/  logs/" -ForegroundColor Green
