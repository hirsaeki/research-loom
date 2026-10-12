[CmdletBinding()]
param(
    [Parameter(Mandatory)][string]$SourceDocx,
    [Parameter(Mandatory)][string]$OutputPdf,
    [Parameter(Mandatory)][string]$ReceiptPath
)
$ErrorActionPreference = 'Stop'
$source = (Resolve-Path -LiteralPath $SourceDocx).Path
$pdf = [IO.Path]::GetFullPath($OutputPdf)
$receipt = [IO.Path]::GetFullPath($ReceiptPath)
if ($source -eq $pdf -or $source -eq $receipt -or $pdf -eq $receipt -or (Test-Path -LiteralPath $pdf) -or (Test-Path -LiteralPath $receipt)) {
    throw 'Use distinct source/output/receipt paths; existing outputs are never overwritten.'
}
$sourceDigest = 'sha256:' + (Get-FileHash -LiteralPath $source -Algorithm SHA256).Hash.ToLowerInvariant()
$archive = [IO.Compression.ZipFile]::OpenRead($source)
try {
    $reader = [IO.StreamReader]::new($archive.GetEntry('word/document.xml').Open())
    try { [xml]$xml = $reader.ReadToEnd() } finally { $reader.Dispose() }
    $ns = [Xml.XmlNamespaceManager]::new($xml.NameTable)
    $ns.AddNamespace('w', 'http://schemas.openxmlformats.org/wordprocessingml/2006/main')
    $parts = @($xml.SelectNodes('//w:sectPr', $ns) | ForEach-Object { $_.GetAttribute('part', 'urn:research-loom:publication') })
} finally { $archive.Dispose() }
if ($parts.Count -lt 12 -or @($parts | Where-Object { -not $_ }).Count) {
    throw 'Source is not a managed formal Publication DOCX.'
}
$word = New-Object -ComObject Word.Application
$word.Visible = $false
$word.DisplayAlerts = 0
try {
    $document = $word.Documents.Open($source, $false, $true)
    try {
        if ($document.Sections.Count -ne $parts.Count) { throw 'Word changed the formal section structure.' }
        $null = $document.Fields.Update()
        foreach ($toc in $document.TablesOfContents) { $toc.Update() }
        foreach ($story in $document.StoryRanges) {
            $range = $story
            while ($null -ne $range) {
                $null = $range.Fields.Update()
                $range = $range.NextStoryRange
            }
        }
        foreach ($toc in $document.TablesOfContents) { $toc.Update() }
        $document.Repaginate()
        $bodyIndex = [Array]::IndexOf($parts, 'body') + 1
        if ($parts[$bodyIndex - 2] -eq 'contents') {
            $lastContents = $document.Sections.Item($bodyIndex - 1).Range.Duplicate
            $null = $lastContents.MoveEnd(1, -1)
            $lastContents.Collapse(0)
            if ($lastContents.Information(3) % 2) {
                # M has no introduction whose oddPage break could supply the
                # mandatory blank reverse after an odd-length contents part.
                $lastContents.InsertBefore("`f `r")
                $document.Repaginate()
            }
        }
        $first = $document.Sections.Item($bodyIndex).Range.Duplicate
        $first.Collapse(1)
        if ($first.Information(3) % 2) {
            # Physical parity cannot use an evenPage break: Word would change
            # restarted logical page 1 to 2. Pad only the preceding section.
            $padding = $document.Sections.Item($bodyIndex - 1).Range.Duplicate
            $null = $padding.MoveEnd(1, -1)
            $padding.Collapse(0)
            $padding.InsertBefore("`f `r")
        }
        foreach ($toc in $document.TablesOfContents) { $toc.UpdatePageNumbers() }
        $document.Repaginate()
        for ($attempt = 0; $attempt -lt 3; $attempt++) {
            for ($i = 0; $i -lt $parts.Count; $i++) {
                $null = $document.Bookmarks.Add(('RL_' + $parts[$i]), $document.Sections.Item($i + 1).Range)
            }
            # Exporting bookmarks materializes Word's final print pagination.
            # The only overwritten PDF is this invocation's own first export.
            $document.ExportAsFixedFormat($pdf, 17, $false, 0, 0, 1, 1, 0, $true, $true, 2)
            $ranges = @{}
            for ($i = 0; $i -lt $parts.Count; $i++) {
                $section = $document.Sections.Item($i + 1)
                $first = $section.Range.Duplicate
                $first.Collapse(1)
                $last = $section.Range.Duplicate
                $null = $last.MoveEnd(1, -1)
                $last.Collapse(0)
                $ranges[$parts[$i]] = @($first.Information(3), $last.Information(3))
            }
            if (-not ($ranges['body'][0] % 2)) { break }
            if ($attempt -lt 2) {
                $padding = $document.Sections.Item($bodyIndex - 1).Range.Duplicate
                $null = $padding.MoveEnd(1, -1)
                $padding.Collapse(0)
                $padding.InsertBefore("`f `r")
                foreach ($toc in $document.TablesOfContents) { $toc.UpdatePageNumbers() }
                $document.Repaginate()
            }
        }
        if ($ranges['body'][0] % 2) { throw 'Body still does not open on a left physical page.' }
        $pdfDigest = 'sha256:' + (Get-FileHash -LiteralPath $pdf -Algorithm SHA256).Hash.ToLowerInvariant()
        $hostReceipt = @{source_docx_digest=$sourceDigest; pdf_digest=$pdfDigest; software='Microsoft Word'; software_version=$word.Version; fields_updated=$true; page_ranges=$ranges}
        $hostReceipt | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath $receipt -Encoding utf8
    } finally { $document.Close(0) }
} finally { $word.Quit() }
if (('sha256:' + (Get-FileHash -LiteralPath $source -Algorithm SHA256).Hash.ToLowerInvariant()) -ne $sourceDigest) {
    throw 'Source DOCX changed during rendering.'
}
Write-Output "Rendered PDF: $pdf"
Write-Output "Host receipt: $receipt"
