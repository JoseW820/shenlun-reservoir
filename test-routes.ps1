param(
    [string]$ConfigPath = (Join-Path $PSScriptRoot 'sources.json'),
    [string]$BaseUrl,
    [int]$TimeoutSec,
    [string]$OutFile = (Join-Path $PSScriptRoot 'route-test-results.json')
)

$ErrorActionPreference = 'Stop'
$config = Get-Content -LiteralPath $ConfigPath -Raw -Encoding UTF8 | ConvertFrom-Json
if (-not $BaseUrl)    { $BaseUrl = [string]$config.baseUrl }
if (-not $TimeoutSec) { $TimeoutSec = [int]$config.timeoutSec }
$BaseUrl = $BaseUrl.TrimEnd('/')

function Get-PlainText([string]$s) {
    if (-not $s) { return '' }
    $t = [regex]::Replace($s, '(?s)<(script|style)\b.*?</\1>', ' ')
    $t = [regex]::Replace($t, '<[^>]+>', ' ')
    $t = [System.Net.WebUtility]::HtmlDecode($t)
    return ([regex]::Replace($t, '\s+', ' ')).Trim()
}

$results = foreach ($src in $config.sources) {
    $url = $BaseUrl + [string]$src.path
    $sw = [Diagnostics.Stopwatch]::StartNew()
    $row = [ordered]@{
        id = [string]$src.id; name = [string]$src.name; type = [string]$src.type
        path = [string]$src.path; url = $url; quota = [int]$src.quota
        status = 'error'; httpStatus = $null; feedType = $null; feedTitle = $null
        itemCount = 0; firstTitle = $null; firstLink = $null; firstPubDate = $null
        firstBodyChars = 0; avgBodyChars = 0
        elapsedMs = 0; error = $null
    }
    try {
        $resp = Invoke-WebRequest -Uri $url -TimeoutSec $TimeoutSec -UseBasicParsing `
            -Headers @{ 'User-Agent' = 'rsshub-local-test/1.0' }
        $row.httpStatus = [int]$resp.StatusCode
        $body = [string]$resp.Content

        $isRss  = $body -match '<rss\b'
        $isAtom = $body -match '<feed\b'
        $row.feedType = if ($isRss) { 'RSS' } elseif ($isAtom) { 'Atom' } else { 'NOT_A_FEED' }
        $null = $body -match '<title(?:\s[^>]*)?>(.*?)</title>'
        $row.feedTitle = [System.Net.WebUtility]::HtmlDecode($Matches[1])

        $itemPattern = if ($isAtom) { '(?s)<entry\b.*?</entry>' } else { '(?s)<item\b.*?</item>' }
        $items = [regex]::Matches($body, $itemPattern)
        $row.itemCount = $items.Count

        if ($items.Count -gt 0) {
            $first = $items[0].Value
            $null = $first -match '<title(?:\s[^>]*)?>(.*?)</title>'
            $row.firstTitle = [System.Net.WebUtility]::HtmlDecode(($Matches[1] -replace '^\s*<!\[CDATA\[|\]\]>\s*$', '')).Trim()
            $lp = if ($isAtom) { '<link[^>]*href="([^"]+)"' } else { '<link>(.*?)</link>' }
            $null = $first -match $lp
            $row.firstLink = $Matches[1]
            $dp = if ($isAtom) { '<(?:updated|published)>(.*?)</(?:updated|published)>' } else { '<pubDate>(.*?)</pubDate>' }
            $null = $first -match $dp
            if ($Matches.Count -gt 1) { $row.firstPubDate = $Matches[1] }

            # 正文长度：抽样前 5 条求均值，判断是否带全文
            $dsc = if ($isAtom) { '(?s)<content[^>]*>(.*?)</content>' } else { '(?s)<description>(.*?)</description>' }
            $lens = @()
            foreach ($it in ($items | Select-Object -First 5)) {
                $null = $it.Value -match $dsc
                if ($Matches.Count -gt 1) { $lens += (Get-PlainText $Matches[1]).Length }
            }
            if ($lens.Count -gt 0) {
                $row.firstBodyChars = $lens[0]
                $row.avgBodyChars = [int](($lens | Measure-Object -Average).Average)
            }
        }

        $row.status = if ($row.feedType -eq 'NOT_A_FEED') { 'not-a-feed' }
                     elseif ($row.itemCount -eq 0) { 'empty' } else { 'ok' }
    }
    catch { $row.error = $_.Exception.Message }
    $row.elapsedMs = [int]$sw.ElapsedMilliseconds
    [pscustomobject]$row
}

$results | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath $OutFile -Encoding UTF8

$results | Format-Table -AutoSize -Property @(
    @{ n='类型';   e={ $_.type } }
    @{ n='来源';   e={ $_.name } }
    @{ n='路径';   e={ $_.path } }
    @{ n='状态';   e={ $_.status } }
    @{ n='HTTP';   e={ $_.httpStatus } }
    @{ n='条目';   e={ $_.itemCount } }
    @{ n='配额';   e={ $_.quota } }
    @{ n='均正文'; e={ $_.avgBodyChars } }
    @{ n='耗时ms'; e={ $_.elapsedMs } }
)

Write-Output ''
Write-Output '=== 可用源的首条样本 ==='
$results | Where-Object { $_.itemCount -gt 0 } | ForEach-Object {
    Write-Output ("[{0}] {1}" -f $_.name, $_.firstTitle)
    Write-Output ("     {0}" -f $_.firstLink)
}
Write-Output ''
$bad = $results | Where-Object { $_.status -ne 'ok' }
if ($bad) {
    Write-Output '=== 未通过（需注意：可能是路由失效，也可能是该源本周无更新）==='
    $bad | ForEach-Object { Write-Output ("  {0,-24} {1,-10} {2}" -f $_.name, $_.status, $_.error) }
}
$okCount = ($results | Where-Object { $_.status -eq 'ok' }).Count
Write-Output ''
Write-Output ("汇总: {0}/{1} 可用，可用源配额合计 {2} 条" -f $okCount, $results.Count,
    (($results | Where-Object { $_.status -eq 'ok' } | Measure-Object quota -Sum).Sum))
Write-Output "结果文件: $OutFile"
