# Keeps a Cloudflare quick tunnel open to the local backend, restarting it if it drops, forever.
# A quick tunnel gets a NEW https://*.trycloudflare.com hostname every time it (re)starts — there is no
# fixed link without owning a domain in Cloudflare. To stay reachable anyway, each time a new hostname
# appears this script publishes it to the `endpoints` table in Supabase (row id "backend", not a secret:
# it's the public URL itself). The dashboard and the daily QA routine read that row to find the live
# backend, so nobody needs to re-paste a link after a restart.
$ErrorActionPreference = "Continue"
$root = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)  # .../command_center
$cloudflared = "C:\Program Files (x86)\cloudflared\cloudflared.exe"
$log = Join-Path $root "data\tunnel-loop.log"
New-Item -ItemType Directory -Force -Path (Split-Path $log) | Out-Null

function Get-EnvValue($name) {
    $line = Get-Content (Join-Path $root ".env") -ErrorAction SilentlyContinue | Where-Object { $_ -match "^$name=" } | Select-Object -First 1
    if ($line) { return ($line -replace "^$name=", "").Trim() }
    return ""
}

function Publish-Url($url) {
    $supabaseUrl = Get-EnvValue "SUPABASE_URL"
    $secretKey = Get-EnvValue "SUPABASE_SECRET_KEY"
    if (-not $supabaseUrl -or -not $secretKey) {
        "$(Get-Date -Format o)  Supabase not configured, skipping URL publish" | Add-Content -Path $log
        return
    }
    try {
        $headers = @{ "apikey" = $secretKey; "Authorization" = "Bearer $secretKey"; "Content-Type" = "application/json"; "Prefer" = "resolution=merge-duplicates,return=minimal" }
        $body = @{ id = "backend"; url = $url; updated_at = (Get-Date).ToUniversalTime().ToString("o") } | ConvertTo-Json -Compress
        Invoke-RestMethod -Method Post -Uri "$supabaseUrl/rest/v1/endpoints?on_conflict=id" -Headers $headers -Body $body | Out-Null
        "$(Get-Date -Format o)  published $url to Supabase" | Add-Content -Path $log
    } catch {
        "$(Get-Date -Format o)  failed to publish url: $_" | Add-Content -Path $log
    }
}

while ($true) {
    "$(Get-Date -Format o)  starting tunnel" | Add-Content -Path $log
    $tunnelLog = Join-Path $root "data\tunnel-current.log"
    Remove-Item $tunnelLog -ErrorAction SilentlyContinue
    $proc = Start-Process -FilePath $cloudflared -ArgumentList "tunnel","--url","http://127.0.0.1:8765" -RedirectStandardError $tunnelLog -RedirectStandardOutput $tunnelLog -NoNewWindow -PassThru

    $published = $false
    for ($i = 0; $i -lt 30 -and -not $published; $i++) {
        Start-Sleep -Seconds 1
        if (Test-Path $tunnelLog) {
            $match = Select-String -Path $tunnelLog -Pattern "https://[a-z0-9-]+\.trycloudflare\.com" -ErrorAction SilentlyContinue | Select-Object -First 1
            if ($match) {
                $url = $match.Matches[0].Value
                Publish-Url $url
                $published = $true
            }
        }
    }
    $proc.WaitForExit()
    Get-Content $tunnelLog -ErrorAction SilentlyContinue | Add-Content -Path $log
    "$(Get-Date -Format o)  tunnel exited, restarting in 5s" | Add-Content -Path $log
    Start-Sleep -Seconds 5
}
