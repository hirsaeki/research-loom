[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [ValidatePattern('^[0-9a-f]{40}$')]
    [string]$ExpectedHead,

    [string]$Workspace = (Join-Path $env:TEMP 'misco-ai-2026-probe2'),

    [string]$EvidenceRoot,

    [string]$ExpectedProjectId = 'PRJ-1',

    [string]$ExpectedProjectTitle = 'Fixture project'
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$script:Utf8NoBom = New-Object System.Text.UTF8Encoding -ArgumentList $false
$script:EvidenceRoot = $null
$script:Launcher = $null
$script:AttentionStatusInput = $null
$script:Assertions = @()
$script:ProbeResult = [ordered]@{
    schema_version = '0.1.0'
    probe = 'misco-probe2-profile-migration-f7-g3'
    status = 'RUNNING'
    started_at = [DateTime]::UtcNow.ToString('o')
    finished_at = $null
    repository_head = $null
    expected_head = $ExpectedHead
    workspace = '%TEMP%\misco-ai-2026-probe2'
    evidence_root = $null
    mode = $null
    run_start_binding = $null
    source_binding = $null
    target_binding = $null
    advancement_event_id = $null
    target_profiles = @()
    assertions = $script:Assertions
    error = $null
}

function Write-Utf8NoBom {
    param(
        [Parameter(Mandatory = $true)][string]$Path,
        [Parameter(Mandatory = $true)][AllowEmptyString()][string]$Text
    )
    $parent = Split-Path -Parent $Path
    if ($parent -and -not (Test-Path -LiteralPath $parent)) {
        New-Item -ItemType Directory -Path $parent -Force | Out-Null
    }
    [System.IO.File]::WriteAllText($Path, $Text, $script:Utf8NoBom)
}

function Write-JsonFile {
    param(
        [Parameter(Mandatory = $true)][string]$Path,
        [Parameter(Mandatory = $true)]$Value
    )
    $json = ConvertTo-Json -InputObject $Value -Depth 100
    Write-Utf8NoBom -Path $Path -Text ($json + [Environment]::NewLine)
}

function Read-JsonFile {
    param([Parameter(Mandatory = $true)][string]$Path)
    return (Get-Content -LiteralPath $Path -Raw -Encoding UTF8 | ConvertFrom-Json)
}

function Get-NormalizedJson {
    param($Value)
    return (ConvertTo-Json -InputObject $Value -Depth 100 -Compress)
}

function Add-Pass {
    param(
        [Parameter(Mandatory = $true)][string]$Name,
        $Actual = $null
    )
    $script:Assertions += [ordered]@{
        name = $Name
        status = 'PASS'
        actual = $Actual
    }
}

function Assert-True {
    param(
        [Parameter(Mandatory = $true)][string]$Name,
        [Parameter(Mandatory = $true)][bool]$Condition,
        $Actual = $null
    )
    if (-not $Condition) {
        $script:Assertions += [ordered]@{
            name = $Name
            status = 'FAIL'
            actual = $Actual
        }
        throw "Probe assertion failed: $Name"
    }
    Add-Pass -Name $Name -Actual $Actual
}

function Assert-Equal {
    param(
        [Parameter(Mandatory = $true)][string]$Name,
        $Expected,
        $Actual
    )
    if ((Get-NormalizedJson $Expected) -ne (Get-NormalizedJson $Actual)) {
        $script:Assertions += [ordered]@{
            name = $Name
            status = 'FAIL'
            expected = $Expected
            actual = $Actual
        }
        throw "Probe assertion failed: $Name"
    }
    Add-Pass -Name $Name -Actual $Actual
}

function Assert-TextEqual {
    param(
        [Parameter(Mandatory = $true)][string]$Name,
        [Parameter(Mandatory = $true)][AllowEmptyString()][string]$Expected,
        [Parameter(Mandatory = $true)][AllowEmptyString()][string]$Actual
    )
    if ($Expected -cne $Actual) {
        $script:Assertions += [ordered]@{
            name = $Name
            status = 'FAIL'
            expected_sha256 = (Get-StringSha256 $Expected)
            actual_sha256 = (Get-StringSha256 $Actual)
        }
        throw "Probe assertion failed: $Name"
    }
    Add-Pass -Name $Name -Actual (Get-StringSha256 $Actual)
}

function Get-StringSha256 {
    param([AllowEmptyString()][string]$Value)
    $bytes = $script:Utf8NoBom.GetBytes($Value)
    $sha = [System.Security.Cryptography.SHA256]::Create()
    try {
        return ([BitConverter]::ToString($sha.ComputeHash($bytes))).Replace('-', '').ToLowerInvariant()
    }
    finally {
        $sha.Dispose()
    }
}

function Get-CommandDisplay {
    param([string]$Command, [string[]]$Arguments)
    $parts = @()
    $parts += ('"' + $Command.Replace('"', '\"') + '"')
    foreach ($arg in $Arguments) {
        if ($arg -match '[\s"]') {
            $parts += ('"' + $arg.Replace('"', '\"') + '"')
        }
        else {
            $parts += $arg
        }
    }
    return ($parts -join ' ')
}

function Invoke-LoomJson {
    param(
        [Parameter(Mandatory = $true)][string]$Name,
        [Parameter(Mandatory = $true)][string[]]$Arguments
    )

    $commandRoot = Join-Path $script:EvidenceRoot 'commands'
    New-Item -ItemType Directory -Path $commandRoot -Force | Out-Null
    $stdoutPath = Join-Path $commandRoot ($Name + '.stdout.json')
    $stderrPath = Join-Path $commandRoot ($Name + '.stderr.txt')
    $commandPath = Join-Path $commandRoot ($Name + '.command.txt')
    Write-Utf8NoBom -Path $commandPath -Text ((Get-CommandDisplay -Command $script:Launcher -Arguments $Arguments) + [Environment]::NewLine)

    $oldErrorActionPreference = $ErrorActionPreference
    $ErrorActionPreference = 'Continue'
    try {
        $stdoutLines = @(& $script:Launcher @Arguments 2> $stderrPath)
        $exitCode = $LASTEXITCODE
    }
    finally {
        $ErrorActionPreference = $oldErrorActionPreference
    }

    $raw = $stdoutLines -join [Environment]::NewLine
    Write-Utf8NoBom -Path $stdoutPath -Text ($raw + [Environment]::NewLine)
    if (-not (Test-Path -LiteralPath $stderrPath)) {
        Write-Utf8NoBom -Path $stderrPath -Text ''
    }

    if ($exitCode -ne 0) {
        $stderr = Get-Content -LiteralPath $stderrPath -Raw -ErrorAction SilentlyContinue
        throw "research-loom command '$Name' failed with exit code $exitCode. See $stderrPath. $stderr"
    }

    try {
        $parsed = $raw | ConvertFrom-Json
    }
    catch {
        throw "research-loom command '$Name' returned non-JSON output. See $stdoutPath. $($_.Exception.Message)"
    }

    return [pscustomobject]@{
        Value = $parsed
        Raw = $raw
        StdoutPath = $stdoutPath
        StderrPath = $stderrPath
    }
}

function Assert-NotTruncated {
    param(
        [Parameter(Mandatory = $true)][string]$Name,
        $Value
    )
    $property = $Value.PSObject.Properties['truncated']
    if ($null -ne $property) {
        Assert-True -Name ($Name + ' is not truncated') -Condition (-not [bool]$property.Value) -Actual $property.Value
    }
}

function Find-CurrentGeneration {
    param($History)
    $matches = @(
        $History.generations | Where-Object {
            $_.project_config_digest -eq $History.current.project_config_digest -and
            $_.effective_profile_set_digest -eq $History.current.effective_profile_set_digest
        }
    )
    if ($matches.Count -gt 1) {
        throw 'profile history contains more than one archived document for the current generation'
    }
    return $(if ($matches.Count -eq 1) { $matches[0] } else { $null })
}

function Get-CurrentGeneration {
    param($History)
    $current = Find-CurrentGeneration -History $History
    Assert-True -Name 'profile history contains the current archived generation' -Condition ($null -ne $current) -Actual ($null -ne $current)
    return $current
}

function Get-ProfileKeys {
    param($EffectiveProfileSet)
    return @(
        $EffectiveProfileSet.effective_profiles |
            ForEach-Object { "$($_.profile_type)|$($_.profile_id)|$($_.profile_version)" } |
            Sort-Object
    )
}

function Get-DirectRequestKeys {
    param($ProjectConfig)
    $keys = @()
    foreach ($type in @('research', 'organization', 'narrative', 'publication')) {
        $collection = $ProjectConfig.profile_requests.$type
        foreach ($request in @($collection)) {
            if ($null -ne $request) {
                $keys += "$($request.profile_type)|$($request.profile_id)|$($request.version)"
            }
        }
    }
    return @($keys | Sort-Object)
}

function Get-SemanticConfigProjection {
    param($Config)
    $excluded = @('profile_requests', 'provenance', 'configuration_digest')
    $result = [ordered]@{}
    foreach ($property in @($Config.PSObject.Properties | Sort-Object Name)) {
        if ($excluded -notcontains $property.Name) {
            $result[$property.Name] = $property.Value
        }
    }
    return [pscustomobject]$result
}

function Capture-PublicState {
    param([Parameter(Mandatory = $true)][string]$Phase)

    $phaseRoot = Join-Path $script:EvidenceRoot $Phase
    New-Item -ItemType Directory -Path $phaseRoot -Force | Out-Null

    $doctor = Invoke-LoomJson -Name "$Phase-doctor" -Arguments @('doctor', '--workspace', $Workspace, '--json')
    $status = Invoke-LoomJson -Name "$Phase-status" -Arguments @('status', '--workspace', $Workspace, '--view', 'detail', '--json')
    $resume = Invoke-LoomJson -Name "$Phase-resume" -Arguments @('resume', '--workspace', $Workspace, '--view', 'detail', '--json')
    $history = Invoke-LoomJson -Name "$Phase-profile-history" -Arguments @('profile', 'history', '--workspace', $Workspace, '--json')
    $attention = Invoke-LoomJson -Name "$Phase-attention-status" -Arguments @('action', 'submit', '--workspace', $Workspace, '--view', 'detail', '--json', $script:AttentionStatusInput)
    $materials = Invoke-LoomJson -Name "$Phase-materials" -Arguments @('external', 'materials', 'list', '--workspace', $Workspace, '--limit', '100', '--json')
    $inputs = Invoke-LoomJson -Name "$Phase-research-inputs" -Arguments @('research-input', 'list', '--workspace', $Workspace, '--limit', '100', '--json')
    $exhibits = Invoke-LoomJson -Name "$Phase-exhibits" -Arguments @('exhibit', 'list', '--workspace', $Workspace, '--json')
    $packages = Invoke-LoomJson -Name "$Phase-packages" -Arguments @('research-package', 'list', '--workspace', $Workspace, '--limit', '100', '--json')
    $compositions = Invoke-LoomJson -Name "$Phase-compositions" -Arguments @('writer-composition', 'list', '--workspace', $Workspace, '--limit', '64', '--json')

    Assert-True -Name "$Phase doctor is OK" -Condition ($doctor.Value.status -eq 'OK') -Actual $doctor.Value.status
    Assert-True -Name "$Phase status is OK" -Condition ($status.Value.status -eq 'OK') -Actual $status.Value.status
    Assert-True -Name "$Phase resume is OK" -Condition ($resume.Value.status -eq 'OK') -Actual $resume.Value.status
    Assert-True -Name "$Phase profile history is OK" -Condition ($history.Value.status -eq 'OK') -Actual $history.Value.status
    Assert-True -Name "$Phase attention status succeeded" -Condition ($attention.Value.status -eq 'SUCCEEDED') -Actual $attention.Value.status
    foreach ($inventory in @(
        @{ Name = 'materials'; Value = $materials.Value },
        @{ Name = 'research inputs'; Value = $inputs.Value },
        @{ Name = 'exhibits'; Value = $exhibits.Value },
        @{ Name = 'packages'; Value = $packages.Value },
        @{ Name = 'compositions'; Value = $compositions.Value }
    )) {
        Assert-True -Name ("$Phase " + $inventory.Name + ' status is OK') -Condition ($inventory.Value.status -eq 'OK') -Actual $inventory.Value.status
    }
    Assert-NotTruncated -Name "$Phase materials" -Value $materials.Value
    Assert-NotTruncated -Name "$Phase research inputs" -Value $inputs.Value
    Assert-NotTruncated -Name "$Phase packages" -Value $packages.Value
    Assert-NotTruncated -Name "$Phase compositions" -Value $compositions.Value

    foreach ($row in @(
        @{ Name = 'doctor'; Result = $doctor },
        @{ Name = 'status'; Result = $status },
        @{ Name = 'resume'; Result = $resume },
        @{ Name = 'profile-history'; Result = $history },
        @{ Name = 'attention-status'; Result = $attention },
        @{ Name = 'materials'; Result = $materials },
        @{ Name = 'research-inputs'; Result = $inputs },
        @{ Name = 'exhibits'; Result = $exhibits },
        @{ Name = 'packages'; Result = $packages },
        @{ Name = 'compositions'; Result = $compositions }
    )) {
        Copy-Item -LiteralPath $row.Result.StdoutPath -Destination (Join-Path $phaseRoot ($row.Name + '.json')) -Force
    }

    return [pscustomobject]@{
        Doctor = $doctor
        Status = $status
        Resume = $resume
        History = $history
        Attention = $attention
        Materials = $materials
        Inputs = $inputs
        Exhibits = $exhibits
        Packages = $packages
        Compositions = $compositions
    }
}

$oldPythonIoEncoding = $env:PYTHONIOENCODING
$oldConsoleOutputEncoding = [Console]::OutputEncoding
$oldOutputEncoding = $OutputEncoding

try {
    [Console]::OutputEncoding = New-Object System.Text.UTF8Encoding -ArgumentList $false
    $OutputEncoding = New-Object System.Text.UTF8Encoding -ArgumentList $false
    $env:PYTHONIOENCODING = 'utf-8'

    $repoRoot = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '..\..')).Path
    $script:Launcher = Join-Path $repoRoot 'research-loom.cmd'
    $resolveRequest = Join-Path $repoRoot 'projects\misco-ai-2026\probe2-profile-resolve.json'
    $expectedResolveRequestSha256 = '1d898e051aa3483437d1a8aea47e5896bf32b2c328a16b80e4bee02bfd3b3b5b'

    $defaultWorkspace = [System.IO.Path]::GetFullPath((Join-Path $env:TEMP 'misco-ai-2026-probe2'))
    $Workspace = [System.IO.Path]::GetFullPath($Workspace)
    $script:ProbeResult.workspace = if ($Workspace -eq $defaultWorkspace) { '%TEMP%\misco-ai-2026-probe2' } else { $Workspace }
    Assert-True -Name 'running on Windows' -Condition ([Environment]::OSVersion.Platform -eq [PlatformID]::Win32NT) -Actual ([Environment]::OSVersion.Platform.ToString())
    Assert-True -Name 'workspace exists' -Condition (Test-Path -LiteralPath $Workspace -PathType Container) -Actual $Workspace
    Assert-True -Name 'production Windows launcher exists' -Condition (Test-Path -LiteralPath $script:Launcher -PathType Leaf) -Actual $script:Launcher
    Assert-True -Name 'repository runtime environment is provisioned' -Condition (Test-Path -LiteralPath (Join-Path $repoRoot '.venv\Scripts\python.exe') -PathType Leaf) -Actual (Join-Path $repoRoot '.venv\Scripts\python.exe')

    $head = (& git -C $repoRoot rev-parse HEAD).Trim()
    Assert-Equal -Name 'repository HEAD matches requested acceptance generation' -Expected $ExpectedHead -Actual $head
    $script:ProbeResult.repository_head = $head

    $worktree = @(& git -C $repoRoot status --porcelain --untracked-files=all)
    Assert-True -Name 'repository worktree is clean' -Condition ($worktree.Count -eq 0) -Actual ($worktree -join [Environment]::NewLine)

    $requestHash = (Get-FileHash -LiteralPath $resolveRequest -Algorithm SHA256).Hash.ToLowerInvariant()
    Assert-Equal -Name 'checked-in probe2 resolve request has expected SHA-256' -Expected $expectedResolveRequestSha256 -Actual $requestHash

    $evidenceRootWasExplicit = -not [string]::IsNullOrWhiteSpace($EvidenceRoot)
    if (-not $evidenceRootWasExplicit) {
        $baseEvidenceRoot = Join-Path $env:TEMP ('research-loom-probe2-misco-migration-' + $ExpectedHead.Substring(0, 12))
        $EvidenceRoot = $baseEvidenceRoot
        $attempt = 0
        while (Test-Path -LiteralPath $EvidenceRoot) {
            $attempt += 1
            $EvidenceRoot = ('{0}-rerun-{1:d2}' -f $baseEvidenceRoot, $attempt)
        }
    }
    $script:EvidenceRoot = [System.IO.Path]::GetFullPath($EvidenceRoot)
    $script:ProbeResult.evidence_root = $script:EvidenceRoot
    Assert-True -Name 'selected evidence root is new' -Condition (-not (Test-Path -LiteralPath $script:EvidenceRoot)) -Actual $script:EvidenceRoot
    New-Item -ItemType Directory -Path $script:EvidenceRoot | Out-Null
    New-Item -ItemType Directory -Path (Join-Path $script:EvidenceRoot 'inputs') | Out-Null

    Copy-Item -LiteralPath $resolveRequest -Destination (Join-Path $script:EvidenceRoot 'inputs\probe2-profile-resolve.json')
    $script:AttentionStatusInput = Join-Path $script:EvidenceRoot 'inputs\attention-status.json'
    Write-JsonFile -Path $script:AttentionStatusInput -Value ([ordered]@{
        action_type = 'research_attention.status'
        payload = [ordered]@{}
    })

    Write-JsonFile -Path (Join-Path $script:EvidenceRoot 'environment.json') -Value ([ordered]@{
        repository_head = $head
        expected_head = $ExpectedHead
        powershell = $PSVersionTable.PSVersion.ToString()
        os = [Environment]::OSVersion.VersionString
        resolve_request_sha256 = $requestHash
        workspace = $script:ProbeResult.workspace
    })

    Write-Host '[1/5] Capturing public pre-migration state...'
    $before = Capture-PublicState -Phase 'before'

    Assert-Equal -Name 'source project id is the intended historical Probe2 project' -Expected $ExpectedProjectId -Actual $before.Resume.Value.project.project_id
    Assert-Equal -Name 'source project title is unchanged historical Probe2 title' -Expected $ExpectedProjectTitle -Actual $before.Resume.Value.project.title
    Assert-True -Name 'no pending confirmations before migration' -Condition (@($before.Status.Value.pending_confirmations).Count -eq 0) -Actual (@($before.Status.Value.pending_confirmations).Count)
    Assert-True -Name 'no pending Human Decisions before migration' -Condition (@($before.Status.Value.pending_human_decisions).Count -eq 0) -Actual (@($before.Status.Value.pending_human_decisions).Count)
    Assert-True -Name 'no pending Runs before migration' -Condition (@($before.Status.Value.pending_runs).Count -eq 0) -Actual (@($before.Status.Value.pending_runs).Count)

    $script:ProbeResult.run_start_binding = [ordered]@{
        project_config_digest = $before.History.Value.current.project_config_digest
        effective_profile_set_digest = $before.History.Value.current.effective_profile_set_digest
        snapshot = $before.Status.Value.snapshot
    }

    $expectedTargetRequests = @(
        'narrative|misco.writer|1.1.0',
        'publication|misco.publication|1.3.0',
        'research|misco.workspace-continuity.exact-locator|1.0.0'
    ) | Sort-Object
    $expectedTargetProfiles = @(
        'narrative|misco.writer|1.1.0',
        'publication|misco.publication|1.3.0',
        'research|misco.workspace-continuity.exact-locator|1.0.0'
    ) | Sort-Object

    $currentGenerationBefore = Find-CurrentGeneration -History $before.History.Value
    $alreadyTarget = $false
    if ($null -ne $currentGenerationBefore) {
        $alreadyTarget = (Get-NormalizedJson (Get-ProfileKeys -EffectiveProfileSet $currentGenerationBefore.effective_profile_set)) -eq (Get-NormalizedJson $expectedTargetProfiles)
    }
    $script:ProbeResult.mode = if ($alreadyTarget) { 'NOOP_VERIFY' } else { 'ADVANCE' }

    $targetDir = Join-Path $script:EvidenceRoot 'target-generation'
    if ($script:ProbeResult.mode -eq 'ADVANCE') {
        Write-Host '[2/5] Resolving exact production target generation...'
        $resolve = Invoke-LoomJson -Name 'resolve-target' -Arguments @(
            'profile', 'resolve',
            '--workspace', $Workspace,
            '--output', $targetDir,
            '--json', $resolveRequest
        )
        Assert-True -Name 'profile resolve status is OK' -Condition ($resolve.Value.status -eq 'OK') -Actual $resolve.Value.status
        Assert-True -Name 'profile resolve changes direct requests' -Condition ([bool]$resolve.Value.profile_request_changed) -Actual $resolve.Value.profile_request_changed
        Assert-Equal -Name 'resolve source binding matches captured source project config' -Expected $before.History.Value.current.project_config_digest -Actual $resolve.Value.source_project_config_digest
        $resolution = Read-JsonFile -Path (Join-Path $targetDir 'resolution.json')
        Assert-Equal -Name 'resolve output and resolution document agree on target EPS digest' -Expected $resolve.Value.target_effective_profile_set_digest -Actual $resolution.target_effective_profile_set_digest
    }
    else {
        Write-Host '[2/5] Workspace already exposes the production target; preparing an exact NOOP verification...'
        New-Item -ItemType Directory -Path $targetDir | Out-Null
        Write-JsonFile -Path (Join-Path $targetDir 'project-config.json') -Value $currentGenerationBefore.project_config
        Write-JsonFile -Path (Join-Path $targetDir 'effective-profile-set.json') -Value $currentGenerationBefore.effective_profile_set
        $manifestFiles = @(
            (Join-Path $repoRoot 'profiles\research\misco-workspace-continuity\profile.json'),
            (Join-Path $repoRoot 'profiles\narrative\misco\profile.json'),
            (Join-Path $repoRoot 'profiles\publication\misco\profile.json')
        )
        $resolution = [pscustomobject][ordered]@{
            schema_version = '0.1.0'
            source_project_config_digest = $before.History.Value.current.project_config_digest
            target_project_config_digest = $before.History.Value.current.project_config_digest
            target_effective_profile_set_digest = $before.History.Value.current.effective_profile_set_digest
            profile_request_changed = $false
            profile_manifest_files = $manifestFiles
            mode = 'NOOP_VERIFY'
        }
        Write-JsonFile -Path (Join-Path $targetDir 'resolution.json') -Value $resolution
        Add-Pass -Name 'workspace already at exact production target; replacement resolve is intentionally skipped on rerun' -Actual $expectedTargetProfiles
    }

    $targetConfig = Read-JsonFile -Path (Join-Path $targetDir 'project-config.json')
    $targetEps = Read-JsonFile -Path (Join-Path $targetDir 'effective-profile-set.json')

    Assert-Equal -Name 'resolved target keeps source project id' -Expected $before.Resume.Value.project.project_id -Actual $targetConfig.project.project_id
    Assert-Equal -Name 'resolved target keeps source project title' -Expected $before.Resume.Value.project.title -Actual $targetConfig.project.title
    Assert-Equal -Name 'resolved target keeps source project objective' -Expected $before.Resume.Value.project.objective -Actual $targetConfig.project.objective
    Assert-Equal -Name 'resolved target keeps source project scope' -Expected $before.Resume.Value.project.scope -Actual $targetConfig.scope
    Assert-Equal -Name 'resolved target keeps source Research Question seeds' -Expected $before.Resume.Value.research_questions.seeds -Actual $targetConfig.research_questions.seeds
    Assert-Equal -Name 'resolved target keeps source baseline Research Attention' -Expected $before.Resume.Value.research_attention.baseline -Actual $targetConfig.research_attention

    $targetRequests = Get-DirectRequestKeys -ProjectConfig $targetConfig
    Assert-Equal -Name 'target direct Profile requests are exactly the intended continuity+Writer+Publication set' -Expected $expectedTargetRequests -Actual $targetRequests

    $targetProfiles = Get-ProfileKeys -EffectiveProfileSet $targetEps
    Assert-Equal -Name 'target Effective Profile Set is exactly the intended production migration set' -Expected $expectedTargetProfiles -Actual $targetProfiles
    Assert-True -Name 'target Effective Profile Set contains no fixture Profile' -Condition (-not (@($targetEps.effective_profiles | Where-Object { $_.profile_id -like 'fixture.*' }).Count)) -Actual $targetProfiles
    $script:ProbeResult.target_profiles = $targetProfiles

    Assert-Equal -Name 'resolution target Project Config digest matches target document' -Expected $resolution.target_project_config_digest -Actual $targetConfig.configuration_digest

    Write-Host '[3/5] Applying/verifying the target through public profile advance...'
    $advanceInput = Join-Path $script:EvidenceRoot 'inputs\profile-advance.json'
    $advanceRequest = [ordered]@{
        project_config_file = (Join-Path $targetDir 'project-config.json')
        effective_profile_set_file = (Join-Path $targetDir 'effective-profile-set.json')
        profile_manifest_files = @($resolution.profile_manifest_files)
        origin = 'issue-336-f7-local-probe'
    }
    Write-JsonFile -Path $advanceInput -Value $advanceRequest
    $advance = Invoke-LoomJson -Name 'advance-target' -Arguments @(
        'profile', 'advance',
        '--workspace', $Workspace,
        '--json', $advanceInput
    )
    Assert-True -Name 'profile advance status is OK' -Condition ($advance.Value.status -eq 'OK') -Actual $advance.Value.status
    $expectedAdvanceResult = if ($script:ProbeResult.mode -eq 'ADVANCE') { 'ADVANCED' } else { 'NOOP' }
    Assert-Equal -Name 'profile advance result matches probe mode' -Expected $expectedAdvanceResult -Actual $advance.Value.result

    Write-Host '[4/5] Reopening through new CLI processes and capturing public post-migration state...'
    $after = Capture-PublicState -Phase 'after'

    Assert-Equal -Name 'project identity/title/objective/scope unchanged after Profile advancement' -Expected $before.Resume.Value.project -Actual $after.Resume.Value.project
    Assert-Equal -Name 'active Research lineage unchanged' -Expected $before.Status.Value.active_lineage -Actual $after.Status.Value.active_lineage
    Assert-Equal -Name 'Research Snapshot unchanged' -Expected $before.Status.Value.snapshot -Actual $after.Status.Value.snapshot
    Assert-Equal -Name 'authoritative Research Questions unchanged' -Expected $before.Resume.Value.research_questions.authoritative -Actual $after.Resume.Value.research_questions.authoritative
    Assert-Equal -Name 'Research Question candidates unchanged' -Expected $before.Resume.Value.research_questions.candidates -Actual $after.Resume.Value.research_questions.candidates
    Assert-Equal -Name 'active Research Attention map unchanged' -Expected $before.Resume.Value.research_attention.active_map -Actual $after.Resume.Value.research_attention.active_map
    Assert-Equal -Name 'effective Research Attention unchanged' -Expected $before.Resume.Value.research_attention.effective -Actual $after.Resume.Value.research_attention.effective
    Assert-Equal -Name 'stored Research Attention maps unchanged' -Expected $before.Resume.Value.research_attention.stored_maps -Actual $after.Resume.Value.research_attention.stored_maps
    Assert-Equal -Name 'public Attention status active map unchanged' -Expected $before.Attention.Value.data.active_map -Actual $after.Attention.Value.data.active_map
    Assert-Equal -Name 'public Attention status effective items unchanged' -Expected $before.Attention.Value.data.effective_attention -Actual $after.Attention.Value.data.effective_attention
    Assert-Equal -Name 'pending/recent workflow projection unchanged' -Expected $before.Resume.Value.workflow -Actual $after.Resume.Value.workflow

    Assert-TextEqual -Name 'external material inventory unchanged' -Expected $before.Materials.Raw -Actual $after.Materials.Raw
    Assert-TextEqual -Name 'project research-input inventory unchanged' -Expected $before.Inputs.Raw -Actual $after.Inputs.Raw
    Assert-TextEqual -Name 'Research Exhibit inventory unchanged' -Expected $before.Exhibits.Raw -Actual $after.Exhibits.Raw
    Assert-TextEqual -Name 'historical Research Package inventory unchanged' -Expected $before.Packages.Raw -Actual $after.Packages.Raw
    Assert-TextEqual -Name 'historical Writer composition inventory unchanged' -Expected $before.Compositions.Raw -Actual $after.Compositions.Raw

    Assert-Equal -Name 'post-migration current Project Config digest matches resolved target' -Expected $resolution.target_project_config_digest -Actual $after.History.Value.current.project_config_digest
    Assert-Equal -Name 'post-migration status binding matches target Project Config' -Expected $resolution.target_project_config_digest -Actual $after.Status.Value.bindings.project_config.digest
    Assert-Equal -Name 'post-migration resume binding matches target Project Config' -Expected $resolution.target_project_config_digest -Actual $after.Resume.Value.research_state.bindings.project_config.digest
    Assert-Equal -Name 'post-migration current EPS digest matches resolved target' -Expected $resolution.target_effective_profile_set_digest -Actual $after.History.Value.current.effective_profile_set_digest
    Assert-Equal -Name 'post-migration status binding matches target EPS' -Expected $resolution.target_effective_profile_set_digest -Actual $after.Status.Value.bindings.effective_profile_set.digest
    Assert-Equal -Name 'post-migration resume binding matches target EPS' -Expected $resolution.target_effective_profile_set_digest -Actual $after.Resume.Value.research_state.bindings.effective_profile_set.digest
    if ($script:ProbeResult.mode -eq 'ADVANCE') {
        Assert-True -Name 'exactly one profile advancement event was appended' -Condition (@($after.History.Value.events).Count -eq (@($before.History.Value.events).Count + 1)) -Actual (@($after.History.Value.events).Count)
        $probeEvents = @(
            $after.History.Value.events | Where-Object {
                $_.origin -eq 'issue-336-f7-local-probe' -and
                $_.old_binding.project_config_digest -eq $before.History.Value.current.project_config_digest -and
                $_.old_binding.effective_profile_set_digest -eq $before.History.Value.current.effective_profile_set_digest -and
                $_.new_binding.project_config_digest -eq $after.History.Value.current.project_config_digest -and
                $_.new_binding.effective_profile_set_digest -eq $after.History.Value.current.effective_profile_set_digest
            }
        )
        Assert-True -Name 'exactly one new append-only advancement event binds source and target generations' -Condition ($probeEvents.Count -eq 1) -Actual $probeEvents.Count
        $event = $probeEvents[0]
        Assert-Equal -Name 'advancement event preserves exact Research Snapshot' -Expected $before.Status.Value.snapshot -Actual $event.research_snapshot
        Assert-Equal -Name 'advance response event matches persisted advancement event' -Expected $advance.Value.event_id -Actual $event.event_id
    }
    else {
        Assert-Equal -Name 'NOOP rerun appends no profile advancement event' -Expected (@($before.History.Value.events).Count) -Actual (@($after.History.Value.events).Count)
        $probeEvents = @(
            $after.History.Value.events | Where-Object {
                $_.new_binding.project_config_digest -eq $after.History.Value.current.project_config_digest -and
                $_.new_binding.effective_profile_set_digest -eq $after.History.Value.current.effective_profile_set_digest
            }
        )
        Assert-True -Name 'NOOP verification can trace the current target to a prior advancement event' -Condition ($probeEvents.Count -ge 1) -Actual $probeEvents.Count
        $event = @($probeEvents | Sort-Object applied_at -Descending)[0]
    }
    Assert-Equal -Name 'migration advancement event records no Research State mutation' -Expected $false -Actual $event.research_state_mutation_performed

    $afterGeneration = Get-CurrentGeneration -History $after.History.Value
    Assert-Equal -Name 'reopened current generation exposes intended target Profiles' -Expected $expectedTargetProfiles -Actual (Get-ProfileKeys -EffectiveProfileSet $afterGeneration.effective_profile_set)
    $oldGenerationStillPresent = @(
        $after.History.Value.generations | Where-Object {
            $_.project_config_digest -eq $event.old_binding.project_config_digest -and
            $_.effective_profile_set_digest -eq $event.old_binding.effective_profile_set_digest
        }
    )
    Assert-True -Name 'migration source Profile generation remains archived and readable' -Condition ($oldGenerationStillPresent.Count -eq 1) -Actual $oldGenerationStillPresent.Count
    $sourceGeneration = $oldGenerationStillPresent[0]
    $sourceDirectRequests = Get-DirectRequestKeys -ProjectConfig $sourceGeneration.project_config
    Assert-True -Name 'archived migration source includes fixture.generic-narrative@1.0.0' -Condition ($sourceDirectRequests -contains 'narrative|fixture.generic-narrative|1.0.0') -Actual $sourceDirectRequests
    Assert-True -Name 'archived migration source includes fixture.publication@1.0.0' -Condition ($sourceDirectRequests -contains 'publication|fixture.publication|1.0.0') -Actual $sourceDirectRequests
    Assert-Equal -Name 'target preserves all non-Profile Project Config semantics' -Expected (Get-SemanticConfigProjection $sourceGeneration.project_config) -Actual (Get-SemanticConfigProjection $targetConfig)

    $script:ProbeResult.source_binding = [ordered]@{
        project_config_digest = $event.old_binding.project_config_digest
        effective_profile_set_digest = $event.old_binding.effective_profile_set_digest
        snapshot = $event.research_snapshot
    }
    $script:ProbeResult.target_binding = [ordered]@{
        project_config_digest = $after.History.Value.current.project_config_digest
        effective_profile_set_digest = $after.History.Value.current.effective_profile_set_digest
        snapshot = $after.Status.Value.snapshot
    }
    $script:ProbeResult.advancement_event_id = $event.event_id

    Write-Host '[5/5] Writing final machine-readable probe result...'
    $script:ProbeResult.status = 'PASS'
}
catch {
    $script:ProbeResult.status = 'FAIL'
    $script:ProbeResult.error = [ordered]@{
        message = $_.Exception.Message
        type = $_.Exception.GetType().FullName
        script_stack_trace = $_.ScriptStackTrace
    }
}
finally {
    $script:ProbeResult.finished_at = [DateTime]::UtcNow.ToString('o')
    $script:ProbeResult.assertions = @($script:Assertions)
    if ($script:EvidenceRoot -and (Test-Path -LiteralPath $script:EvidenceRoot)) {
        Write-JsonFile -Path (Join-Path $script:EvidenceRoot 'probe-result.json') -Value $script:ProbeResult
    }
    if ($null -eq $oldPythonIoEncoding) {
        Remove-Item Env:PYTHONIOENCODING -ErrorAction SilentlyContinue
    }
    else {
        $env:PYTHONIOENCODING = $oldPythonIoEncoding
    }
    [Console]::OutputEncoding = $oldConsoleOutputEncoding
    $OutputEncoding = $oldOutputEncoding
}

if ($script:ProbeResult.status -ne 'PASS') {
    Write-Error ("MISCO Probe2 Profile migration probe FAILED. Evidence: {0}. Error: {1}" -f $script:EvidenceRoot, $script:ProbeResult.error.message)
    exit 1
}

Write-Host ''
Write-Host 'MISCO Probe2 Profile migration probe: PASS'
Write-Host ("Evidence: {0}" -f $script:EvidenceRoot)
Write-Host ("Event: {0}" -f $script:ProbeResult.advancement_event_id)
Write-Host 'Use probe-result.json plus before/after/target-generation as the #336 F7 / #337 G3 operator evidence.'
exit 0
