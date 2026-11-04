function Invoke-TocAppendixPrefixOnDocument {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory = $true)]
        [object]$Document,

        [switch]$UpdateNativeTocs,

        [string]$Prefix = ([string][char]0x4ed8)
    )

    if (-not $Document.Bookmarks.Exists('AUTO_APPENDIX')) { throw 'AUTO_APPENDIX bookmark is missing.' }
    $appendixToc = $null
    for ($i = 1; $i -le $Document.TablesOfContents.Count; $i++) {
        $toc = $Document.TablesOfContents.Item($i)
        if ($toc.Range.Fields.Count -gt 0 -and
            ([string]$toc.Range.Fields.Item(1).Code.Text) -match '(?i)\\b\s+"?AUTO_APPENDIX"?(?=\s|$)') {
            if ($null -ne $appendixToc) { throw 'More than one AUTO_APPENDIX TOC was found.' }
            $appendixToc = $toc
        }
    }
    if ($null -eq $appendixToc) { throw 'No AUTO_APPENDIX TOC was found.' }

    # A previous invocation locks cached results so Word print/export cannot
    # recalculate them. Unlock before any native TOC update.
    for ($i = 1; $i -le $appendixToc.Range.Fields.Count; $i++) {
        $appendixToc.Range.Fields.Item($i).Locked = $false
    }
    if ($UpdateNativeTocs) {
        for ($i = 1; $i -le $Document.TablesOfContents.Count; $i++) {
            $Document.TablesOfContents.Item($i).Update()
        }
    }

    $Document.Repaginate()
    # Refresh all numeric references before inserting any prefix. Updating a
    # later field may refresh earlier results through the enclosing hyperlinks.
    for ($i = 1; $i -le $appendixToc.Range.Fields.Count; $i++) {
        $field = $appendixToc.Range.Fields.Item($i)
        if ([string]$field.Code.Text -match '(?i)\bPAGEREF\b') {
            $field.Locked = $false
            $null = $field.Update()
        }
    }
    $checked = 0
    $changed = 0
    for ($i = 1; $i -le $appendixToc.Range.Fields.Count; $i++) {
        $field = $appendixToc.Range.Fields.Item($i)
        if ([string]$field.Code.Text -notmatch '(?i)\bPAGEREF\b') { continue }
        $checked++
        $result = $field.Result.Duplicate()
        $text = ([string]$result.Text).Replace("`r", '').Replace("`n", '').Replace([string][char]7, '').Trim()
        if (-not $text.StartsWith($Prefix, [StringComparison]::Ordinal)) {
            $result.InsertBefore($Prefix)
            $changed++
        }
    }
    if ($checked -eq 0) { throw 'AUTO_APPENDIX TOC contains no PAGEREF entries.' }

    $footerGapsRemoved = 0
    foreach ($section in $Document.Sections) {
        for ($footerType = 1; $footerType -le 3; $footerType++) {
            $footer = $section.Footers.Item($footerType)
            if (-not $footer.Exists -or $footer.Range.Fields.Count -eq 0) { continue }
            foreach ($pageField in @($footer.Range.Fields)) {
                if ([string]$pageField.Code.Text -notmatch '(?i)^\s*PAGE\b') { continue }
                $fieldStart = [int]$pageField.Code.Start
                $chars = @($footer.Range.Characters)
                $prefixEnd = -1
                foreach ($char in $chars) {
                    if ([int]$char.End -le $fieldStart -and [string]$char.Text -eq $Prefix) {
                        $prefixEnd = [int]$char.End
                    }
                }
                if ($prefixEnd -lt 0) { continue }
                $gaps = @($chars | Where-Object {
                    [int]$_.Start -ge $prefixEnd -and
                    [int]$_.End -le $fieldStart -and
                    $_.Text.Length -gt 0 -and
                    [char]::IsWhiteSpace($_.Text[0])
                } | Sort-Object Start -Descending)
                foreach ($gap in $gaps) {
                    [void]$gap.Delete()
                    $footerGapsRemoved++
                }
            }
        }
    }

    # Prevent Word's PDF export from rebuilding the cached appendix result.
    # The next invocation unlocks these fields before updating.
    for ($i = 1; $i -le $appendixToc.Range.Fields.Count; $i++) {
        $appendixToc.Range.Fields.Item($i).Locked = $true
    }

    return [pscustomobject]@{
        Entries = $checked
        Changed = $changed
        FooterGapsRemoved = $footerGapsRemoved
        Prefix = $Prefix
    }
}
