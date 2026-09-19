# Skill Office Agent demo scripts (PowerShell)
# Usage:  powershell -File D:\skill-office-agent\examples\run_demo.ps1

$py = if ($env:MIMO_PYTHON) { $env:MIMO_PYTHON } else { "python" }
$root = "D:\skill-office-agent"
Set-Location $root

Write-Host "=== 1) List skills ===" -ForegroundColor Cyan
& $py run_cli.py skills

Write-Host "`n=== 2) Route only ===" -ForegroundColor Cyan
& $py run_cli.py route "找到销售表并统计各区域销售额，生成报告并起草同步邮件"

Write-Host "`n=== 3) Multi-skill serial run ===" -ForegroundColor Cyan
& $py run_cli.py run "找到销售表并统计各区域销售额，生成报告并起草同步邮件" --args-file "$root\data\workspace\demo_args.json"

Write-Host "`n=== 4) Web search with local KB fallback ===" -ForegroundColor Cyan
& $py run_cli.py run "搜索一下远程办公协作要点" --skills "web-search"

Write-Host "`n=== 5) Direct Function Calling tool ===" -ForegroundColor Cyan
& $py run_cli.py call-tool search_files --args "{\"query\":\"sales\",\"root\":\"$($root -replace '\\','/')/data\"}"

Write-Host "`nDone. Outputs in data\workspace\ and logs\" -ForegroundColor Green
