param(
  [ValidateSet('chrome','edge')][string]$Browser='edge',
  [ValidateRange(1024,65535)][int]$Port=9222,
  [string]$ProfileDir=(Join-Path $env:LOCALAPPDATA 'CDPReviewCollector\profile'),
  [string]$Url='about:blank',
  [switch]$Interactive
)
$ErrorActionPreference='Stop'
$paths = if ($Browser -eq 'edge') { @("${env:ProgramFiles(x86)}\Microsoft\Edge\Application\msedge.exe", "$env:ProgramFiles\Microsoft\Edge\Application\msedge.exe") } else { @("$env:ProgramFiles\Google\Chrome\Application\chrome.exe", "${env:ProgramFiles(x86)}\Google\Chrome\Application\chrome.exe", "$env:LOCALAPPDATA\Google\Chrome\Application\chrome.exe") }
$exe=$paths | Where-Object { Test-Path -LiteralPath $_ } | Select-Object -First 1
if (!$exe) { throw '找不到浏览器，请确认已安装 Chrome 或 Edge。' }
if (Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue) { throw "端口 $Port 已使用；先 probe 确认，不重复启动。" }
$resolved=[IO.Path]::GetFullPath($ProfileDir)
if ($resolved -match '(?i)\\(Google\\Chrome|Microsoft\\Edge)\\User Data(\\|$)') { throw '请使用专用目录，不能使用浏览器日常默认用户目录。' }
if ($resolved.Contains('"') -or $Url.Contains('"')) { throw '参数不能包含双引号。' }
New-Item -ItemType Directory -Force -Path $resolved | Out-Null
Start-Process -FilePath $exe -ArgumentList @("--remote-debugging-address=127.0.0.1", "--remote-debugging-port=$Port", "--user-data-dir=`"$resolved`"", '--no-first-run', "`"$Url`"") -WindowStyle $(if ($Interactive) {'Normal'} else {'Hidden'})
Write-Output "CDP http://127.0.0.1:$Port；请在专用浏览器窗口登录。登录状态留本机，不打包该目录。"
