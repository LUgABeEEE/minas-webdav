# SPDX-License-Identifier: Apache-2.0
# Start the loopback proxy if needed and map it to N: through WebClient.
# Requires (both are checked below, because a bare "net use" only says
# "System error 67" and that is impossible to diagnose from the message):
#   * the WebClient service running   (net start WebClient, admin)
#   * BasicAuthLevel = 2             (plain HTTP; the default 1 allows HTTPS only)
$scripts = Split-Path -Parent $MyInvocation.MyCommand.Path
$root = Split-Path -Parent $scripts
$py = if ($env:MIMO_PYTHON) { $env:MIMO_PYTHON } else { "python" }

$svc = Get-Service WebClient -ErrorAction SilentlyContinue
if (-not $svc) { Write-Host "WebClient 服务不存在，无法挂 WebDAV"; exit 1 }
if ($svc.Status -ne 'Running') {
  Write-Host "WebClient 服务未运行。请用管理员 PowerShell 执行：net start WebClient"
  exit 1
}
$params = 'HKLM:\SYSTEM\CurrentControlSet\Services\WebClient\Parameters'
$basic = (Get-ItemProperty $params -ErrorAction SilentlyContinue).BasicAuthLevel
if ($null -ne $basic -and $basic -lt 2) {
  Write-Host "BasicAuthLevel=$basic：明文 HTTP 挂盘需要 2（管理员改注册表后重启 WebClient）"
  exit 1
}

if (-not (Get-NetTCPConnection -LocalPort 8899 -State Listen -ErrorAction SilentlyContinue)) {
  Start-Process -FilePath $py -ArgumentList "-m", "minas_webdav", "proxy" -WorkingDirectory $root -WindowStyle Hidden
  for ($i = 0; $i -lt 20; $i++) {
    Start-Sleep -Milliseconds 500
    if (Get-NetTCPConnection -LocalPort 8899 -State Listen -ErrorAction SilentlyContinue) { break }
  }
}
if (-not (Get-NetTCPConnection -LocalPort 8899 -State Listen -ErrorAction SilentlyContinue)) {
  Write-Host "代理没有起来（8899 未监听）；单独跑一次 python -m minas_webdav proxy 看报错"
  exit 1
}

net use N: /delete /y 2>$null | Out-Null
# The proxy maps /pool0/data onto the drive root, so mount the bare "/" and the
# drive shows the whole pool.
net use N: "http://127.0.0.1:8899/" /persistent:no | Out-Null
if (Test-Path "N:\") { Write-Host "N: OK（根目录即 /pool0/data）" } else { Write-Host "N: FAILED" ; exit 1 }
