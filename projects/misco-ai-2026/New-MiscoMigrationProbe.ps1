[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [ValidatePattern('^[0-9a-f]{40}$')]
    [string]$ExpectedHead,

    [string]$Workspace = $(
        if ($env:RESEARCH_LOOM_WORKSPACES) {
            Join-Path $env:RESEARCH_LOOM_WORKSPACES 'probes\misco-profile-migration'
        }
        else {
            'D:\wsroot\scratch\loom-workspaces\probes\misco-profile-migration'
        }
    ),

    [string]$EvidenceRoot
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$script:Utf8NoBom = New-Object System.Text.UTF8Encoding -ArgumentList $false
$script:Launcher = $null
$script:EvidenceRoot = $null
$script:Assertions = @()
$script:ProbeId = 'misco-production-profile-migration-1.2-to-1.3'
$script:LegacyRef = 'f31efa68c56377fedd3216fd506d2807d55194e0'
$script:ActorId = 'MISCO-MIGRATION-PROBE'
$script:ExpectedProjectId = 'misco-m3-2026'
$script:ExpectedProjectTitle = 'AIの進化とそれがもたらすMISCO企業への影響'
$script:ExpectedSourceProfiles = @(
    'narrative|misco.writer|1.1.0',
    'publication|misco.publication|1.2.0'
)
$script:ExpectedTargetProfiles = @(
    'narrative|misco.writer|1.1.0',
    'publication|misco.publication|1.3.0'
)
$script:ProbeResult = [ordered]@{
    schema_version = '0.1.0'
    probe = $script:ProbeId
    status = 'RUNNING'
    mode = $null
    started_at = [DateTime]::UtcNow.ToString('o')
    finished_at = $null
    repository_head = $null
    expected_head = $ExpectedHead
    legacy_ref = $script:LegacyRef
    workspace = $null
    evidence_root = $null
    source_binding = $null
    target_binding = $null
    advancement_event_id = $null
    seeded_ids = $null
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
    param([string]$Name, $Actual = $null)
    $script:Assertions += [ordered]@{ name = $Name; status = 'PASS'; actual = $Actual }
}

function Assert-True {
    param([string]$Name, [bool]$Condition, $Actual = $null)
    if (-not $Condition) {
        $script:Assertions += [ordered]@{ name = $Name; status = 'FAIL'; actual = $Actual }
        throw "Probe assertion failed: $Name"
    }
    Add-Pass -Name $Name -Actual $Actual
}

function Assert-Equal {
    param([string]$Name, $Expected, $Actual)
    if ((Get-NormalizedJson $Expected) -ne (Get-NormalizedJson $Actual)) {
        $script:Assertions += [ordered]@{ name = $Name; status = 'FAIL'; expected = $Expected; actual = $Actual }
        throw "Probe assertion failed: $Name"
    }
    Add-Pass -Name $Name -Actual $Actual
}

function Assert-TextEqual {
    param([string]$Name, [string]$Expected, [string]$Actual)
    if ($Expected -cne $Actual) {
        $script:Assertions += [ordered]@{ name = $Name; status = 'FAIL' }
        throw "Probe assertion failed: $Name"
    }
    Add-Pass -Name $Name -Actual 'exact text match'
}

function Get-CommandDisplay {
    param([string]$Command, [string[]]$Arguments)
    $parts = @('"' + $Command.Replace('"', '\"') + '"')
    foreach ($arg in $Arguments) {
        if ($arg -match '[\s"]') { $parts += ('"' + $arg.Replace('"', '\"') + '"') }
        else { $parts += $arg }
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

    $oldPreference = $ErrorActionPreference
    $ErrorActionPreference = 'Continue'
    try {
        $stdoutLines = @(& $script:Launcher @Arguments 2> $stderrPath)
        $exitCode = $LASTEXITCODE
    }
    finally {
        $ErrorActionPreference = $oldPreference
    }
    $raw = $stdoutLines -join [Environment]::NewLine
    Write-Utf8NoBom -Path $stdoutPath -Text ($raw + [Environment]::NewLine)
    if (-not (Test-Path -LiteralPath $stderrPath)) { Write-Utf8NoBom -Path $stderrPath -Text '' }

    $parsed = $null
    if (-not [string]::IsNullOrWhiteSpace($raw)) {
        try { $parsed = $raw | ConvertFrom-Json } catch { }
    }
    if ($exitCode -ne 0) {
        $detail = $null
        if ($parsed -and $parsed.issues -and @($parsed.issues).Count -gt 0) {
            $detail = "[$($parsed.issues[0].code)] $($parsed.issues[0].message)"
        }
        if (-not $detail) {
            $stderr = Get-Content -LiteralPath $stderrPath -Raw -ErrorAction SilentlyContinue
            $detail = $stderr.Trim()
        }
        throw "research-loom command '$Name' failed with exit code $exitCode. $detail Evidence: $stdoutPath / $stderrPath"
    }
    if ($null -eq $parsed) {
        throw "research-loom command '$Name' returned non-JSON output. See $stdoutPath"
    }
    return [pscustomobject]@{ Value = $parsed; Raw = $raw; StdoutPath = $stdoutPath; StderrPath = $stderrPath }
}

function Invoke-GitText {
    param([string]$Spec, [string]$OutputPath)
    $oldPreference = $ErrorActionPreference
    $ErrorActionPreference = 'Continue'
    try {
        $lines = @(& git -C $repoRoot show $Spec 2>&1)
        $exitCode = $LASTEXITCODE
    }
    finally { $ErrorActionPreference = $oldPreference }
    if ($exitCode -ne 0) { throw "git show failed for ${Spec}: $($lines -join [Environment]::NewLine)" }
    Write-Utf8NoBom -Path $OutputPath -Text (($lines -join [Environment]::NewLine) + [Environment]::NewLine)
}

function Get-ProfileKeys {
    param($EffectiveProfileSet)
    return @(
        $EffectiveProfileSet.effective_profiles |
            ForEach-Object { "$($_.profile_type)|$($_.profile_id)|$($_.profile_version)" } |
            Sort-Object
    )
}

function Get-PackageProfileKeys {
    param($EffectiveProfileSet)
    return @(
        $EffectiveProfileSet.profile_pins |
            ForEach-Object { "$($_.profile_type)|$($_.profile_id)|$($_.profile_version)" } |
            Sort-Object
    )
}

function Get-CurrentGeneration {
    param($History)
    $matches = @(
        $History.generations | Where-Object {
            $_.project_config_digest -eq $History.current.project_config_digest -and
            $_.effective_profile_set_digest -eq $History.current.effective_profile_set_digest
        }
    )
    Assert-True -Name 'profile history has exactly one archived current generation' -Condition ($matches.Count -eq 1) -Actual $matches.Count
    return $matches[0]
}

function Write-ActionInput {
    param([string]$Name, $Value)
    $path = Join-Path $script:EvidenceRoot ('inputs\' + $Name + '.json')
    Write-JsonFile -Path $path -Value $Value
    return $path
}

function Capture-State {
    param([string]$Phase, $Marker)
    $phaseRoot = Join-Path $script:EvidenceRoot $Phase
    New-Item -ItemType Directory -Path $phaseRoot -Force | Out-Null

    $doctor = Invoke-LoomJson -Name "$Phase-doctor" -Arguments @('doctor','--workspace',$Workspace,'--json')
    $status = Invoke-LoomJson -Name "$Phase-status" -Arguments @('status','--workspace',$Workspace,'--view','detail','--json')
    $resume = Invoke-LoomJson -Name "$Phase-resume" -Arguments @('resume','--workspace',$Workspace,'--view','detail','--json')
    $history = Invoke-LoomJson -Name "$Phase-profile-history" -Arguments @('profile','history','--workspace',$Workspace,'--json')
    $attentionInput = Write-ActionInput -Name "$Phase-attention-status-input" -Value ([ordered]@{ action_type='research_attention.status'; payload=[ordered]@{} })
    $attention = Invoke-LoomJson -Name "$Phase-attention-status" -Arguments @('action','submit','--workspace',$Workspace,'--view','detail','--json',$attentionInput)
    $inputs = Invoke-LoomJson -Name "$Phase-research-inputs" -Arguments @('research-input','list','--workspace',$Workspace,'--limit','100','--json')
    $packages = Invoke-LoomJson -Name "$Phase-packages" -Arguments @('research-package','list','--workspace',$Workspace,'--limit','100','--json')
    $compositions = Invoke-LoomJson -Name "$Phase-compositions" -Arguments @('writer-composition','list','--workspace',$Workspace,'--limit','64','--json')
    $package = Invoke-LoomJson -Name "$Phase-package-show" -Arguments @('research-package','show','--workspace',$Workspace,'--package-id',$Marker.package_id,'--json')
    $composition = Invoke-LoomJson -Name "$Phase-composition-show" -Arguments @('writer-composition','show','--workspace',$Workspace,'--composition-id',$Marker.composition_id,'--version',[string]$Marker.composition_version,'--json')

    Assert-True -Name "$Phase doctor OK" -Condition ($doctor.Value.status -eq 'OK') -Actual $doctor.Value.status
    Assert-True -Name "$Phase status OK" -Condition ($status.Value.status -eq 'OK') -Actual $status.Value.status
    Assert-True -Name "$Phase resume OK" -Condition ($resume.Value.status -eq 'OK') -Actual $resume.Value.status
    Assert-True -Name "$Phase history OK" -Condition ($history.Value.status -eq 'OK') -Actual $history.Value.status
    Assert-True -Name "$Phase attention status succeeded" -Condition ($attention.Value.status -eq 'SUCCEEDED') -Actual $attention.Value.status
    Assert-True -Name "$Phase research inputs OK" -Condition ($inputs.Value.status -eq 'OK') -Actual $inputs.Value.status
    Assert-True -Name "$Phase packages OK" -Condition ($packages.Value.status -eq 'OK') -Actual $packages.Value.status
    Assert-True -Name "$Phase compositions OK" -Condition ($compositions.Value.status -eq 'OK') -Actual $compositions.Value.status

    foreach ($row in @(
        @{Name='doctor';Result=$doctor}, @{Name='status';Result=$status}, @{Name='resume';Result=$resume},
        @{Name='profile-history';Result=$history}, @{Name='attention-status';Result=$attention},
        @{Name='research-inputs';Result=$inputs}, @{Name='packages';Result=$packages}, @{Name='compositions';Result=$compositions},
        @{Name='package-show';Result=$package}, @{Name='composition-show';Result=$composition}
    )) {
        Copy-Item -LiteralPath $row.Result.StdoutPath -Destination (Join-Path $phaseRoot ($row.Name + '.json')) -Force
    }

    return [pscustomobject]@{
        Doctor=$doctor; Status=$status; Resume=$resume; History=$history; Attention=$attention;
        Inputs=$inputs; Packages=$packages; Compositions=$compositions; Package=$package; Composition=$composition
    }
}

function Seed-ProbeWorkspace {
    param([string]$LegacyConfigPath, [string]$LegacyEpsPath, [string]$MarkerPath)

    Write-Host '[setup] Initializing durable Workspace from the pinned 1.2.0 production generation...'
    $init = Invoke-LoomJson -Name 'setup-init' -Arguments @('init','--workspace',$Workspace,'--project-config',$LegacyConfigPath,'--effective-profile-set',$LegacyEpsPath,'--json')
    Assert-True -Name 'legacy production init succeeded' -Condition ($init.Value.status -eq 'OK') -Actual $init.Value.status

    $doctor = Invoke-LoomJson -Name 'setup-doctor' -Arguments @('doctor','--workspace',$Workspace,'--json')
    Assert-True -Name 'new durable probe Workspace doctor is OK' -Condition ($doctor.Value.status -eq 'OK') -Actual $doctor.Value.status

    $rqProposeInput = Write-ActionInput -Name 'setup-rq-propose' -Value ([ordered]@{
        action_type='research_question.propose'
        payload=[ordered]@{ text='Which durable migration invariants must remain unchanged when the MISCO Publication Profile advances from 1.2.0 to 1.3.0?' }
        actor_id=$script:ActorId
    })
    $rqPropose = Invoke-LoomJson -Name 'setup-rq-propose' -Arguments @('action','submit','--workspace',$Workspace,'--view','detail','--json',$rqProposeInput)
    $rqId = [string]$rqPropose.Value.data.research_question_candidate.id
    $proposalId = [string]$rqPropose.Value.data.state_delta_proposal_id

    $rqApplyInput = Write-ActionInput -Name 'setup-rq-apply' -Value ([ordered]@{
        action_type='state.apply_candidate'; payload=[ordered]@{ state_delta_proposal_id=$proposalId }; actor_id=$script:ActorId
    })
    $rqApply = Invoke-LoomJson -Name 'setup-rq-apply' -Arguments @('action','submit','--workspace',$Workspace,'--view','detail','--json',$rqApplyInput)
    $confirmInput = Write-ActionInput -Name 'setup-rq-confirm' -Value ([ordered]@{
        confirmation_request_id=[string]$rqApply.Value.confirmation_request.confirmation_request_id; actor_id=$script:ActorId
    })
    $confirmed = Invoke-LoomJson -Name 'setup-rq-confirm' -Arguments @('confirmation','submit','--workspace',$Workspace,'--view','detail','--json',$confirmInput)
    Assert-True -Name 'RQ confirmation requires explicit Human Decision' -Condition ($confirmed.Value.status -eq 'HUMAN_DECISION_REQUIRED') -Actual $confirmed.Value.status
    $decision = $confirmed.Value.decision_request
    $decisionInput = Write-ActionInput -Name 'setup-rq-decision' -Value ([ordered]@{
        request_id=[string]$decision.request_id
        request_digest=[string]$decision.request_digest
        disposition='approve_exact'
        actor_id=$script:ActorId
    })
    $resolved = Invoke-LoomJson -Name 'setup-rq-decision' -Arguments @('decision','resolve','--workspace',$Workspace,'--view','detail','--json',$decisionInput)
    Assert-True -Name 'RQ Human Decision resolved' -Condition ($resolved.Value.status -eq 'RESOLVED') -Actual $resolved.Value.status

    $activeAttentionInput = Write-ActionInput -Name 'setup-attention-propose-active' -Value ([ordered]@{
        action_type='research_attention.propose'
        payload=[ordered]@{ additions=@([ordered]@{ statement='Preserve the durable migration acceptance focus across Profile advancement.' }) }
        actor_id=$script:ActorId
    })
    $activeAttention = Invoke-LoomJson -Name 'setup-attention-propose-active' -Arguments @('action','submit','--workspace',$Workspace,'--view','detail','--json',$activeAttentionInput)
    $activeMapId = [string]$activeAttention.Value.data.attention_map.map_id
    $activateInput = Write-ActionInput -Name 'setup-attention-activate' -Value ([ordered]@{
        action_type='research_attention.activate_candidate'; payload=[ordered]@{ attention_map_id=$activeMapId }; actor_id=$script:ActorId
    })
    $activate = Invoke-LoomJson -Name 'setup-attention-activate' -Arguments @('action','submit','--workspace',$Workspace,'--view','detail','--json',$activateInput)
    $activateConfirmInput = Write-ActionInput -Name 'setup-attention-confirm' -Value ([ordered]@{
        confirmation_request_id=[string]$activate.Value.confirmation_request.confirmation_request_id; actor_id=$script:ActorId
    })
    $activateConfirmed = Invoke-LoomJson -Name 'setup-attention-confirm' -Arguments @('confirmation','submit','--workspace',$Workspace,'--view','detail','--json',$activateConfirmInput)
    Assert-True -Name 'active Attention candidate confirmed' -Condition ($activateConfirmed.Value.status -eq 'SUCCEEDED') -Actual $activateConfirmed.Value.status

    $staleAttentionInput = Write-ActionInput -Name 'setup-attention-propose-stale' -Value ([ordered]@{
        action_type='research_attention.propose'
        payload=[ordered]@{ additions=@([ordered]@{ statement='Keep this second Attention candidate intentionally unactivated across migration.' }) }
        actor_id=$script:ActorId
    })
    $staleAttention = Invoke-LoomJson -Name 'setup-attention-propose-stale' -Arguments @('action','submit','--workspace',$Workspace,'--view','detail','--json',$staleAttentionInput)
    $staleMapId = [string]$staleAttention.Value.data.attention_map.map_id

    $status = Invoke-LoomJson -Name 'setup-status-for-input' -Arguments @('status','--workspace',$Workspace,'--view','detail','--json')
    $probeInputPath = Join-Path $Workspace 'migration-probe-input.txt'
    Write-Utf8NoBom -Path $probeInputPath -Text ("Durable migration probe input. This is operator-supplied working material, not Evidence or a Finding.`n")
    $registerInput = Write-ActionInput -Name 'setup-project-input-register' -Value ([ordered]@{
        file=$probeInputPath
        role='other'
        expected_snapshot_id=[string]$status.Value.snapshot.snapshot_id
        expected_snapshot_digest=[string]$status.Value.snapshot.content_digest
        provenance=[ordered]@{ supplied_by='misco-migration-probe'; purpose='durable Profile migration continuity acceptance' }
    })
    $registered = Invoke-LoomJson -Name 'setup-project-input-register' -Arguments @('research-input','register','--workspace',$Workspace,'--json',$registerInput)
    $inputId = [string]$registered.Value.project_input.input_id

    $packageInput = Write-ActionInput -Name 'setup-package-build' -Value ([ordered]@{
        snapshot_id=[string]$status.Value.snapshot.snapshot_id
        snapshot_digest=[string]$status.Value.snapshot.content_digest
        lineage_ref=[string]$status.Value.active_lineage
        project_config_digest=[string]$status.Value.bindings.project_config.digest
        effective_profile_set_digest=[string]$status.Value.bindings.effective_profile_set.digest
        rq_id=$rqId
        object_ids=@()
        run_ids=@()
        exhibit_ids=@()
        project_input_ids=@($inputId)
        materials=@()
        gap_ids=@()
    })
    $built = Invoke-LoomJson -Name 'setup-package-build' -Arguments @('research-package','build','--workspace',$Workspace,'--json',$packageInput)
    Assert-True -Name 'Research Package built' -Condition ($built.Value.status -eq 'BUILT') -Actual $built.Value.status
    $packageId = [string]$built.Value.package.package_id

    $compositionInput = Write-ActionInput -Name 'setup-composition-capture' -Value ([ordered]@{
        composition_id='COMP-MISCO-MIGRATION-PROBE'
        purpose='Exercise durable Writer-state continuity across a Profile-only migration.'
        audience=@('migration reviewer')
        sections=@(
            [ordered]@{
                section_id='SEC-FRAME'; order=1; heading='Migration framing'; reader_question='What is being migrated?';
                purpose='Frame the adopted Research Question and operator-supplied working material.';
                narrative_stage_refs=@('framing'); semantic_purpose_refs=@('frame_problem');
                messages=@('Describe the bounded migration acceptance context without inventing Findings.');
                opening_intent='State the migration question.'; closing_intent='Hand off to validation.';
                next_section_id='SEC-VALIDATE'; prohibited_claims=@('Do not turn working material into Evidence or a Finding.');
                argument_refs=@(); finding_refs=@(); evidence_refs=@(); source_refs=@(); counter_review_refs=@(); qualifier_refs=@(); limitation_refs=@(); contribution_refs=@(); recommendation_refs=@(); exhibit_refs=@(); gap_refs=@(); material_refs=@(); citation_requirements=@()
            },
            [ordered]@{
                section_id='SEC-VALIDATE'; order=2; heading='Validation still pending'; reader_question='What remains deliberately unresolved?';
                purpose='Keep validation visibly incomplete while preserving the composition.';
                narrative_stage_refs=@('validation'); semantic_purpose_refs=@('test_and_qualify');
                messages=@('Record that no Finding or Argument was invented for this migration probe.');
                previous_section_id='SEC-FRAME'; opening_intent='Preserve the unresolved state.'; closing_intent='Return to research rather than fabricate a result.';
                detailed=$false; argument_refs=@(); finding_refs=@(); evidence_refs=@(); source_refs=@(); counter_review_refs=@(); qualifier_refs=@(); limitation_refs=@(); contribution_refs=@(); recommendation_refs=@(); exhibit_refs=@(); gap_refs=@(); material_refs=@(); citation_requirements=@()
            }
        )
        created_by=[ordered]@{ type='human_or_external_llm'; instruction='Deterministic migration probe fixture; use only the supplied Research Package.' }
    })
    $composition = Invoke-LoomJson -Name 'setup-composition-capture' -Arguments @('writer-composition','capture','--workspace',$Workspace,'--package-id',$packageId,'--json',$compositionInput)
    Assert-True -Name 'Writer Composition captured' -Condition ($composition.Value.status -eq 'CAPTURED') -Actual $composition.Value.status
    $compositionId = [string]$composition.Value.composition.composition_id
    $compositionVersion = [int]$composition.Value.composition.version
    $compositionDigest = [string]$composition.Value.composition.composition_digest
    Assert-True -Name 'Writer Composition remains explicitly incomplete' -Condition ($composition.Value.composition.validation.status -eq 'VALID_WITH_GAPS') -Actual $composition.Value.composition.validation.status
    $selected = Invoke-LoomJson -Name 'setup-composition-select' -Arguments @('writer-composition','select','--workspace',$Workspace,'--composition-id',$compositionId,'--version',[string]$compositionVersion,'--digest',$compositionDigest,'--json')
    Assert-True -Name 'Writer Composition selected' -Condition ($selected.Value.status -eq 'SELECTED') -Actual $selected.Value.status

    $marker = [ordered]@{
        schema_version='0.1.0'
        probe=$script:ProbeId
        state='SEEDED_SOURCE'
        legacy_ref=$script:LegacyRef
        project_id=$script:ExpectedProjectId
        rq_id=$rqId
        active_attention_map_id=$activeMapId
        stale_attention_map_id=$staleMapId
        project_input_id=$inputId
        package_id=$packageId
        composition_id=$compositionId
        composition_version=$compositionVersion
        composition_digest=$compositionDigest
        target_project_config_digest=$null
        target_effective_profile_set_digest=$null
        advancement_event_id=$null
    }
    Write-JsonFile -Path $MarkerPath -Value $marker
    return [pscustomobject]$marker
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
    $Workspace = [System.IO.Path]::GetFullPath($Workspace)
    $script:ProbeResult.workspace = $Workspace

    Assert-True -Name 'running on Windows' -Condition ([Environment]::OSVersion.Platform -eq [PlatformID]::Win32NT) -Actual ([Environment]::OSVersion.Platform.ToString())
    Assert-True -Name 'production Windows launcher exists' -Condition (Test-Path -LiteralPath $script:Launcher -PathType Leaf) -Actual $script:Launcher
    Assert-True -Name 'repository runtime environment is provisioned' -Condition (Test-Path -LiteralPath (Join-Path $repoRoot '.venv\Scripts\python.exe') -PathType Leaf) -Actual (Join-Path $repoRoot '.venv\Scripts\python.exe')

    $tempRoot = [System.IO.Path]::GetFullPath($env:TEMP).TrimEnd('\') + '\'
    Assert-True -Name 'durable probe Workspace is not under OS TEMP' -Condition (-not $Workspace.StartsWith($tempRoot, [System.StringComparison]::OrdinalIgnoreCase)) -Actual $Workspace

    $head = (& git -C $repoRoot rev-parse HEAD).Trim()
    Assert-Equal -Name 'repository HEAD matches requested acceptance generation' -Expected $ExpectedHead -Actual $head
    $script:ProbeResult.repository_head = $head
    $worktree = @(& git -C $repoRoot status --porcelain --untracked-files=all)
    Assert-True -Name 'repository worktree is clean' -Condition ($worktree.Count -eq 0) -Actual ($worktree -join [Environment]::NewLine)
    & git -C $repoRoot cat-file -e ($script:LegacyRef + '^{commit}') 2>$null
    Assert-True -Name 'full Git history contains pinned 1.2.0 source generation' -Condition ($LASTEXITCODE -eq 0) -Actual $script:LegacyRef

    if ([string]::IsNullOrWhiteSpace($EvidenceRoot)) {
        $workspaceParent = Split-Path -Parent $Workspace
        $evidenceParent = Join-Path $workspaceParent '_evidence'
        New-Item -ItemType Directory -Path $evidenceParent -Force | Out-Null
        $base = Join-Path $evidenceParent ('misco-profile-migration-' + $ExpectedHead.Substring(0,12))
        $EvidenceRoot = $base
        $attempt = 0
        while (Test-Path -LiteralPath $EvidenceRoot) {
            $attempt += 1
            $EvidenceRoot = ('{0}-rerun-{1:d2}' -f $base, $attempt)
        }
    }
    $script:EvidenceRoot = [System.IO.Path]::GetFullPath($EvidenceRoot)
    $script:ProbeResult.evidence_root = $script:EvidenceRoot
    Assert-True -Name 'evidence root is outside OS TEMP' -Condition (-not $script:EvidenceRoot.StartsWith($tempRoot, [System.StringComparison]::OrdinalIgnoreCase)) -Actual $script:EvidenceRoot
    Assert-True -Name 'selected evidence root is new' -Condition (-not (Test-Path -LiteralPath $script:EvidenceRoot)) -Actual $script:EvidenceRoot
    New-Item -ItemType Directory -Path (Join-Path $script:EvidenceRoot 'inputs') -Force | Out-Null

    $legacyRoot = Join-Path $script:EvidenceRoot 'legacy-generation'
    New-Item -ItemType Directory -Path $legacyRoot -Force | Out-Null
    $legacyConfigPath = Join-Path $legacyRoot 'project-config.json'
    $legacyEpsPath = Join-Path $legacyRoot 'effective-profile-set.json'
    Invoke-GitText -Spec ($script:LegacyRef + ':projects/misco-ai-2026/project-config.json') -OutputPath $legacyConfigPath
    Invoke-GitText -Spec ($script:LegacyRef + ':projects/misco-ai-2026/effective-profile-set.json') -OutputPath $legacyEpsPath
    $legacyConfig = Read-JsonFile $legacyConfigPath
    $legacyEps = Read-JsonFile $legacyEpsPath
    Assert-Equal -Name 'legacy source project id is production MISCO project' -Expected $script:ExpectedProjectId -Actual $legacyConfig.project.project_id
    Assert-Equal -Name 'legacy source project title is production MISCO title' -Expected $script:ExpectedProjectTitle -Actual $legacyConfig.project.title
    Assert-Equal -Name 'legacy source Profile generation is exactly 1.2.0 production' -Expected $script:ExpectedSourceProfiles -Actual (Get-ProfileKeys $legacyEps)

    $markerPath = Join-Path $Workspace '.misco-migration-probe.json'
    $workspaceExists = Test-Path -LiteralPath $Workspace -PathType Container
    if (-not $workspaceExists) {
        $parent = Split-Path -Parent $Workspace
        New-Item -ItemType Directory -Path $parent -Force | Out-Null
        $marker = Seed-ProbeWorkspace -LegacyConfigPath $legacyConfigPath -LegacyEpsPath $legacyEpsPath -MarkerPath $markerPath
    }
    else {
        Assert-True -Name 'existing probe Workspace carries the deterministic probe marker' -Condition (Test-Path -LiteralPath $markerPath -PathType Leaf) -Actual $markerPath
        $marker = Read-JsonFile $markerPath
        Assert-Equal -Name 'existing Workspace belongs to this probe' -Expected $script:ProbeId -Actual $marker.probe
        Assert-Equal -Name 'existing Workspace was seeded from pinned legacy ref' -Expected $script:LegacyRef -Actual $marker.legacy_ref
    }
    Assert-True -Name 'probe marker state is supported' -Condition (@('SEEDED_SOURCE','MIGRATED_TARGET') -contains [string]$marker.state) -Actual $marker.state
    $script:ProbeResult.seeded_ids = [ordered]@{
        rq_id=$marker.rq_id; active_attention_map_id=$marker.active_attention_map_id; stale_attention_map_id=$marker.stale_attention_map_id;
        project_input_id=$marker.project_input_id; package_id=$marker.package_id; composition_id=$marker.composition_id
    }

    Write-Host '[1/4] Capturing public pre-migration state...'
    $before = Capture-State -Phase 'before' -Marker $marker
    Assert-Equal -Name 'probe Workspace project id is production MISCO project' -Expected $script:ExpectedProjectId -Actual $before.Resume.Value.project.project_id
    Assert-Equal -Name 'probe Workspace project title is production MISCO title' -Expected $script:ExpectedProjectTitle -Actual $before.Resume.Value.project.title
    Assert-True -Name 'seeded RQ is authoritative before migration' -Condition (@($before.Resume.Value.research_questions.authoritative | Where-Object { $_.id -eq $marker.rq_id }).Count -eq 1) -Actual $marker.rq_id
    Assert-Equal -Name 'active Attention map matches seeded map' -Expected $marker.active_attention_map_id -Actual $before.Attention.Value.data.active_map.map_id
    Assert-True -Name 'stale Attention candidate remains stored but inactive' -Condition (@($before.Resume.Value.research_attention.stored_maps | Where-Object { $_.map_id -eq $marker.stale_attention_map_id }).Count -eq 1) -Actual $marker.stale_attention_map_id
    Assert-True -Name 'seeded project input remains listed' -Condition (@($before.Inputs.Value.project_inputs | Where-Object { $_.input_id -eq $marker.project_input_id }).Count -eq 1) -Actual $marker.project_input_id
    Assert-True -Name 'seeded Research Package remains listed' -Condition (@($before.Packages.Value.packages | Where-Object { $_.package_id -eq $marker.package_id }).Count -eq 1) -Actual $marker.package_id
    Assert-True -Name 'seeded Writer Composition remains listed' -Condition (@($before.Compositions.Value.compositions | Where-Object { $_.composition_id -eq $marker.composition_id }).Count -eq 1) -Actual $marker.composition_id
    Assert-Equal -Name 'historical Research Package retains 1.2.0 Profile pins' -Expected $script:ExpectedSourceProfiles -Actual (Get-PackageProfileKeys $before.Package.Value.package.effective_profile_set)

    $manifestFiles = @(
        (Join-Path $repoRoot 'profiles\narrative\misco\profile.json'),
        (Join-Path $repoRoot 'profiles\publication\misco\profile.json')
    )
    $targetRoot = Join-Path $script:EvidenceRoot 'target-generation'
    $currentArchivedBefore = @(
        $before.History.Value.generations | Where-Object {
            $_.project_config_digest -eq $before.History.Value.current.project_config_digest -and
            $_.effective_profile_set_digest -eq $before.History.Value.current.effective_profile_set_digest
        }
    )
    $currentAlreadyTarget = $false
    if ($currentArchivedBefore.Count -eq 1) {
        $currentAlreadyTarget = ((Get-NormalizedJson (Get-ProfileKeys $currentArchivedBefore[0].effective_profile_set)) -eq (Get-NormalizedJson $script:ExpectedTargetProfiles))
    }

    if ($marker.state -eq 'SEEDED_SOURCE' -and -not $currentAlreadyTarget) {
        $script:ProbeResult.mode = 'ADVANCE'
        $resolveInput = Write-ActionInput -Name 'profile-resolve' -Value ([ordered]@{
            profile_manifest_files=$manifestFiles
            request_replacements=@([ordered]@{
                from=[ordered]@{ profile_id='misco.publication'; profile_type='publication'; version='1.2.0' }
                to=[ordered]@{ profile_id='misco.publication'; profile_type='publication'; version='1.3.0' }
            })
            request_additions=@()
        })
        Write-Host '[2/4] Resolving exact 1.3.0 target generation...'
        $resolve = Invoke-LoomJson -Name 'profile-resolve' -Arguments @('profile','resolve','--workspace',$Workspace,'--output',$targetRoot,'--json',$resolveInput)
        Assert-True -Name 'profile resolve succeeded' -Condition ($resolve.Value.status -eq 'OK') -Actual $resolve.Value.status
    }
    else {
        Assert-True -Name 'NOOP/recovery path already exposes the exact target generation' -Condition $currentAlreadyTarget -Actual $(if ($currentArchivedBefore.Count -eq 1) { Get-ProfileKeys $currentArchivedBefore[0].effective_profile_set } else { @() })
        $script:ProbeResult.mode = 'NOOP'
        Write-Host '[2/4] Reconstructing exact current target from public Profile history for NOOP verification...'
        $current = Get-CurrentGeneration -History $before.History.Value
        New-Item -ItemType Directory -Path $targetRoot | Out-Null
        Write-JsonFile -Path (Join-Path $targetRoot 'project-config.json') -Value $current.project_config
        Write-JsonFile -Path (Join-Path $targetRoot 'effective-profile-set.json') -Value $current.effective_profile_set
    }

    $targetConfig = Read-JsonFile (Join-Path $targetRoot 'project-config.json')
    $targetEps = Read-JsonFile (Join-Path $targetRoot 'effective-profile-set.json')
    Assert-Equal -Name 'resolved target Profile generation is exactly current production' -Expected $script:ExpectedTargetProfiles -Actual (Get-ProfileKeys $targetEps)
    Assert-Equal -Name 'target project id unchanged' -Expected $script:ExpectedProjectId -Actual $targetConfig.project.project_id
    Assert-Equal -Name 'target project title unchanged' -Expected $script:ExpectedProjectTitle -Actual $targetConfig.project.title

    $advanceInput = Write-ActionInput -Name 'profile-advance' -Value ([ordered]@{
        project_config_file=(Join-Path $targetRoot 'project-config.json')
        effective_profile_set_file=(Join-Path $targetRoot 'effective-profile-set.json')
        profile_manifest_files=$manifestFiles
        origin='issue-336-f7-durable-replacement-probe'
    })
    Write-Host '[3/4] Applying Profile migration through the public path...'
    $advance = Invoke-LoomJson -Name 'profile-advance' -Arguments @('profile','advance','--workspace',$Workspace,'--json',$advanceInput)
    $expectedAdvanceResult = if ($script:ProbeResult.mode -eq 'ADVANCE') { 'ADVANCED' } else { 'NOOP' }
    Assert-Equal -Name 'profile advance result matches probe mode' -Expected $expectedAdvanceResult -Actual $advance.Value.result

    Write-Host '[4/4] Reopening through public CLI processes and verifying continuity...'
    $after = Capture-State -Phase 'after' -Marker $marker
    Assert-Equal -Name 'project identity/title/objective/scope unchanged' -Expected $before.Resume.Value.project -Actual $after.Resume.Value.project
    Assert-Equal -Name 'active Research lineage unchanged' -Expected $before.Status.Value.active_lineage -Actual $after.Status.Value.active_lineage
    Assert-Equal -Name 'Research Snapshot unchanged' -Expected $before.Status.Value.snapshot -Actual $after.Status.Value.snapshot
    Assert-Equal -Name 'authoritative Research Questions unchanged' -Expected $before.Resume.Value.research_questions.authoritative -Actual $after.Resume.Value.research_questions.authoritative
    Assert-Equal -Name 'Research Question candidates unchanged' -Expected $before.Resume.Value.research_questions.candidates -Actual $after.Resume.Value.research_questions.candidates
    Assert-Equal -Name 'Research Attention projection unchanged' -Expected $before.Resume.Value.research_attention -Actual $after.Resume.Value.research_attention
    Assert-Equal -Name 'public active Attention unchanged' -Expected $before.Attention.Value.data.active_map -Actual $after.Attention.Value.data.active_map
    Assert-Equal -Name 'public effective Attention unchanged' -Expected $before.Attention.Value.data.effective_attention -Actual $after.Attention.Value.data.effective_attention
    Assert-TextEqual -Name 'project-input inventory unchanged' -Expected $before.Inputs.Raw -Actual $after.Inputs.Raw
    Assert-TextEqual -Name 'Research Package inventory unchanged' -Expected $before.Packages.Raw -Actual $after.Packages.Raw
    Assert-TextEqual -Name 'Writer Composition inventory unchanged' -Expected $before.Compositions.Raw -Actual $after.Compositions.Raw
    Assert-TextEqual -Name 'historical Research Package document unchanged' -Expected $before.Package.Raw -Actual $after.Package.Raw
    Assert-TextEqual -Name 'historical Writer Composition document unchanged' -Expected $before.Composition.Raw -Actual $after.Composition.Raw
    Assert-Equal -Name 'historical Research Package still pins 1.2.0 generation' -Expected $script:ExpectedSourceProfiles -Actual (Get-PackageProfileKeys $after.Package.Value.package.effective_profile_set)

    $afterGeneration = Get-CurrentGeneration -History $after.History.Value
    Assert-Equal -Name 'current Workspace generation exposes 1.3.0 production Profiles' -Expected $script:ExpectedTargetProfiles -Actual (Get-ProfileKeys $afterGeneration.effective_profile_set)
    Assert-Equal -Name 'status current Project Config matches Profile history' -Expected $after.History.Value.current.project_config_digest -Actual $after.Status.Value.bindings.project_config.digest
    Assert-Equal -Name 'status current EPS matches Profile history' -Expected $after.History.Value.current.effective_profile_set_digest -Actual $after.Status.Value.bindings.effective_profile_set.digest

    if ($script:ProbeResult.mode -eq 'ADVANCE') {
        Assert-True -Name 'exactly one advancement event appended' -Condition (@($after.History.Value.events).Count -eq (@($before.History.Value.events).Count + 1)) -Actual (@($after.History.Value.events).Count)
        $events = @($after.History.Value.events | Where-Object { $_.origin -eq 'issue-336-f7-durable-replacement-probe' })
        Assert-True -Name 'one durable replacement advancement event exists' -Condition ($events.Count -eq 1) -Actual $events.Count
        $event = $events[0]
        Assert-Equal -Name 'advancement event preserves Research Snapshot' -Expected $before.Status.Value.snapshot -Actual $event.research_snapshot
        Assert-Equal -Name 'advance response event matches persisted event' -Expected $advance.Value.event_id -Actual $event.event_id
        $marker.state = 'MIGRATED_TARGET'
        $marker.target_project_config_digest = $after.History.Value.current.project_config_digest
        $marker.target_effective_profile_set_digest = $after.History.Value.current.effective_profile_set_digest
        $marker.advancement_event_id = $event.event_id
        Write-JsonFile -Path $markerPath -Value $marker
    }
    else {
        Assert-Equal -Name 'NOOP rerun appends no advancement event' -Expected (@($before.History.Value.events).Count) -Actual (@($after.History.Value.events).Count)
        Assert-True -Name 'NOOP rerun retains prior advancement event' -Condition (@($after.History.Value.events | Where-Object { $_.origin -eq 'issue-336-f7-durable-replacement-probe' }).Count -ge 1) -Actual (@($after.History.Value.events).Count)
        $event = @($after.History.Value.events | Where-Object { $_.origin -eq 'issue-336-f7-durable-replacement-probe' } | Sort-Object applied_at -Descending)[0]
        if ($marker.state -ne 'MIGRATED_TARGET') {
            $marker.state = 'MIGRATED_TARGET'
            $marker.target_project_config_digest = $after.History.Value.current.project_config_digest
            $marker.target_effective_profile_set_digest = $after.History.Value.current.effective_profile_set_digest
            $marker.advancement_event_id = $event.event_id
            Write-JsonFile -Path $markerPath -Value $marker
        }
    }

    Assert-Equal -Name 'advancement records no Research State mutation' -Expected $false -Actual $event.research_state_mutation_performed
    $sourceGeneration = @($after.History.Value.generations | Where-Object {
        $_.project_config_digest -eq $event.old_binding.project_config_digest -and
        $_.effective_profile_set_digest -eq $event.old_binding.effective_profile_set_digest
    })
    Assert-True -Name '1.2.0 source generation remains archived and readable' -Condition ($sourceGeneration.Count -eq 1) -Actual $sourceGeneration.Count
    Assert-Equal -Name 'archived migration source remains 1.2.0 production generation' -Expected $script:ExpectedSourceProfiles -Actual (Get-ProfileKeys $sourceGeneration[0].effective_profile_set)

    $script:ProbeResult.source_binding = [ordered]@{
        project_config_digest=$event.old_binding.project_config_digest
        effective_profile_set_digest=$event.old_binding.effective_profile_set_digest
        snapshot=$event.research_snapshot
    }
    $script:ProbeResult.target_binding = [ordered]@{
        project_config_digest=$after.History.Value.current.project_config_digest
        effective_profile_set_digest=$after.History.Value.current.effective_profile_set_digest
        snapshot=$after.Status.Value.snapshot
    }
    $script:ProbeResult.advancement_event_id = $event.event_id
    $script:ProbeResult.status = 'PASS'
}
catch {
    $script:ProbeResult.status = 'FAIL'
    $script:ProbeResult.error = [ordered]@{
        message=$_.Exception.Message
        type=$_.Exception.GetType().FullName
        script_stack_trace=$_.ScriptStackTrace
    }
}
finally {
    $script:ProbeResult.finished_at = [DateTime]::UtcNow.ToString('o')
    $script:ProbeResult.assertions = @($script:Assertions)
    if ($script:EvidenceRoot -and (Test-Path -LiteralPath $script:EvidenceRoot)) {
        Write-JsonFile -Path (Join-Path $script:EvidenceRoot 'probe-result.json') -Value $script:ProbeResult
    }
    if ($null -eq $oldPythonIoEncoding) { Remove-Item Env:PYTHONIOENCODING -ErrorAction SilentlyContinue }
    else { $env:PYTHONIOENCODING = $oldPythonIoEncoding }
    [Console]::OutputEncoding = $oldConsoleOutputEncoding
    $OutputEncoding = $oldOutputEncoding
}

if ($script:ProbeResult.status -ne 'PASS') {
    Write-Error ("MISCO durable Profile migration probe FAILED. Evidence: {0}. Error: {1}" -f $script:EvidenceRoot, $script:ProbeResult.error.message)
    exit 1
}

Write-Host ''
Write-Host 'MISCO durable Profile migration probe: PASS'
Write-Host ("Mode: {0}" -f $script:ProbeResult.mode)
Write-Host ("Workspace: {0}" -f $Workspace)
Write-Host ("Evidence: {0}" -f $script:EvidenceRoot)
Write-Host ("Event: {0}" -f $script:ProbeResult.advancement_event_id)
Write-Host 'Use probe-result.json plus before/after/target-generation as the replacement #336 F7 / #337 G3 live migration evidence.'
exit 0
