"""Shell tab-completion scripts for the QuickPRS CLI.

Generates bash and PowerShell completion scripts that complete:
- Subcommand names
- Flags for the active subcommand
- File paths with .PRS extension
- Template names (--template flag)
- Scanner format names (--format flag)
- Set types for remove/edit commands
- Option paths for set-option (section.attribute)
- List types (systems, talkgroups, channels, frequencies, sets, options)
"""

# All subcommands defined in cli.py run_cli()
SUBCOMMANDS = [
    "create", "build", "fleet",
    "inject", "import-rr", "import-paste", "import-json", "import-scanner",
    "export-json", "export-csv",
    "merge", "clone",
    "remove", "edit", "set-option", "bulk-edit",
    "list", "validate", "capacity", "repair",
    "info", "compare", "dump", "diff-options",
    "iden-templates", "report",
    "freq-tools", "auto-setup",
    "encrypt", "set-nac",
    "health", "suggest", "freq-map",
]

# Inject sub-subcommands
INJECT_TYPES = ["p25", "conv", "talkgroups"]

# Bulk-edit sub-subcommands
BULK_EDIT_TYPES = ["talkgroups", "channels"]

# Freq-tools sub-subcommands
FREQ_TOOLS_TYPES = ["offset", "channel", "tones", "dcs", "nearest"]

# Template names for inject conv --template
TEMPLATE_NAMES = ["murs", "gmrs", "frs", "marine", "noaa"]

# Scanner format names for import-scanner --format
SCANNER_FORMATS = ["uniden", "chirp", "sdrtrunk", "auto"]

# Set types for remove command
SET_TYPES = ["system", "trunk-set", "group-set", "conv-set"]

# List types for list command
LIST_TYPES = ["systems", "talkgroups", "channels", "frequencies",
              "sets", "options"]

# Option section names for set-option (section.attribute)
OPTION_SECTIONS = ["gps", "misc", "audio", "bluetooth", "timedate",
                   "accessory", "mandown", "display"]

# Common option paths for set-option
OPTION_PATHS = [
    "gps.gpsMode", "gps.type", "gps.operationMode", "gps.mapDatum",
    "gps.positionFormat", "gps.elevationUnits", "gps.northingType",
    "gps.gridDigits", "gps.angularUnits", "gps.reportInterval",
    "audio.speakerMode", "audio.pttMode", "audio.noiseCancellation",
    "audio.tones", "audio.cctTimer",
    "bluetooth.friendlyName", "bluetooth.btMode", "bluetooth.btAdminMode",
    "misc.password", "misc.maintenancePassword", "misc.topFpMode",
    "misc.topFpOrient", "misc.topFpIntensity", "misc.topFpTimeout",
    "misc.topFpLedColor", "misc.dateFormat", "misc.p25Optimize",
    "misc.batteryType", "misc.autoRSSIThreshold", "misc.ledEnabled",
    "timedate.time", "timedate.zone", "timedate.date",
    "accessory.noiseCancellation", "accessory.micSelectMode",
    "accessory.pttMode",
    "mandown.inactivityTime", "mandown.warningTime",
]

# Flags per subcommand
_SUBCOMMAND_FLAGS = {
    "info": ["-d", "--detail"],
    "validate": [],
    "create": ["--name", "--author"],
    "build": ["-o", "--output"],
    "fleet": ["--units", "-o", "--output"],
    "inject": [],  # has sub-subcommands
    "import-rr": [
        "--sid", "--url", "--username", "--apikey",
        "--categories", "--tags", "-o", "--output",
    ],
    "import-paste": [
        "--name", "--sysid", "--wacn", "--long-name",
        "--tgs-file", "--freqs-file", "-o", "--output",
    ],
    "import-json": ["-o", "--output"],
    "import-scanner": [
        "--csv", "--format", "--name", "-o", "--output",
    ],
    "export-json": ["-o", "--output", "--compact"],
    "export-csv": [],
    "merge": [
        "--systems", "--channels", "--all", "-o", "--output",
    ],
    "clone": ["-o", "--output"],
    "remove": ["-o", "--output"],
    "edit": [
        "--name", "--author", "--rename-set", "-o", "--output",
    ],
    "set-option": ["--list", "-o", "--output"],
    "bulk-edit": [],  # has sub-subcommands
    "list": [],
    "capacity": [],
    "repair": ["-o", "--output", "--salvage"],
    "report": ["-o", "--output"],
    "compare": ["--detail"],
    "dump": ["-s", "--section", "-x", "--hex"],
    "diff-options": ["--raw"],
    "iden-templates": ["-d", "--detail"],
    "freq-tools": [],  # has sub-subcommands
    "auto-setup": [
        "--sid", "--url", "--username", "--apikey",
        "--categories", "--tags", "-o", "--output",
    ],
    "encrypt": [
        "--set", "--tg", "--all", "--key-id",
        "--decrypt", "-o", "--output",
    ],
    "set-nac": [
        "--set", "--channel", "--nac", "--nac-rx",
        "-o", "--output",
    ],
    "health": [],
    "suggest": [],
    "freq-map": ["--band"],
}

# Flags for inject sub-subcommands
_INJECT_FLAGS = {
    "p25": [
        "--name", "--long-name", "--sysid", "--wacn",
        "--freqs-csv", "--tgs-csv",
        "--iden-base", "--iden-spacing", "-o", "--output",
    ],
    "conv": [
        "--name", "--channels-csv", "--template", "-o", "--output",
    ],
    "talkgroups": [
        "--set", "--tgs-csv", "-o", "--output",
    ],
}

# Flags for bulk-edit sub-subcommands
_BULK_EDIT_FLAGS = {
    "talkgroups": [
        "--set", "--enable-scan", "--disable-scan",
        "--enable-tx", "--disable-tx",
        "--prefix", "--suffix", "-o", "--output",
    ],
    "channels": [
        "--set", "--set-tone", "--clear-tones",
        "--set-power", "-o", "--output",
    ],
}


def generate_bash_completion():
    """Generate bash tab completion script for the quickprs CLI.

    Returns the script as a string. Users install it with:
        eval "$(quickprs --completion bash)"
    """
    subcommands = " ".join(SUBCOMMANDS)
    inject_types = " ".join(INJECT_TYPES)
    bulk_edit_types = " ".join(BULK_EDIT_TYPES)
    freq_tools_types = " ".join(FREQ_TOOLS_TYPES)
    templates = " ".join(TEMPLATE_NAMES)
    scanner_fmts = " ".join(SCANNER_FORMATS)
    set_types = " ".join(SET_TYPES)
    list_types = " ".join(LIST_TYPES)
    option_paths = " ".join(OPTION_PATHS)

    # Build flag completion cases
    flag_cases = []
    for cmd, flags in _SUBCOMMAND_FLAGS.items():
        if flags:
            flag_list = " ".join(flags)
            flag_cases.append(
                f'        {cmd})\n'
                f'            opts="{flag_list}"\n'
                f'            ;;'
            )

    inject_flag_cases = []
    for sub, flags in _INJECT_FLAGS.items():
        flag_list = " ".join(flags)
        inject_flag_cases.append(
            f'            {sub})\n'
            f'                opts="{flag_list}"\n'
            f'                ;;'
        )

    bulk_flag_cases = []
    for sub, flags in _BULK_EDIT_FLAGS.items():
        flag_list = " ".join(flags)
        bulk_flag_cases.append(
            f'            {sub})\n'
            f'                opts="{flag_list}"\n'
            f'                ;;'
        )

    flag_case_block = "\n".join(flag_cases)
    inject_case_block = "\n".join(inject_flag_cases)
    bulk_case_block = "\n".join(bulk_flag_cases)

    return f'''# bash completion for quickprs
# Install: eval "$(quickprs --completion bash)"

_quickprs_complete() {{
    local cur prev words cword
    _init_completion || return

    cur="${{COMP_WORDS[COMP_CWORD]}}"
    prev="${{COMP_WORDS[COMP_CWORD-1]}}"

    local commands="{subcommands}"

    # Complete subcommand at position 1
    if [ $COMP_CWORD -eq 1 ]; then
        COMPREPLY=($(compgen -W "$commands --version --completion" -- "$cur"))
        return
    fi

    local subcmd="${{COMP_WORDS[1]}}"

    # --completion flag value
    if [ "$prev" = "--completion" ]; then
        COMPREPLY=($(compgen -W "bash powershell" -- "$cur"))
        return
    fi

    # --template value completion
    if [ "$prev" = "--template" ]; then
        COMPREPLY=($(compgen -W "{templates}" -- "$cur"))
        return
    fi

    # --format value completion
    if [ "$prev" = "--format" ]; then
        COMPREPLY=($(compgen -W "{scanner_fmts}" -- "$cur"))
        return
    fi

    # PRS file completion for flags that take file paths
    case "$prev" in
        -o|--output|--csv|--freqs-csv|--tgs-csv|--channels-csv|--tgs-file|--freqs-file)
            _filedir '@(PRS|prs|csv|CSV|json|JSON|ini|INI|html|HTML)'
            return
            ;;
    esac

    # inject sub-subcommand
    if [ "$subcmd" = "inject" ]; then
        if [ $COMP_CWORD -eq 3 ]; then
            COMPREPLY=($(compgen -W "{inject_types}" -- "$cur"))
            return
        fi
        if [ $COMP_CWORD -gt 3 ]; then
            local inject_sub="${{COMP_WORDS[3]}}"
            local opts=""
            case "$inject_sub" in
{inject_case_block}
            esac
            COMPREPLY=($(compgen -W "$opts" -- "$cur"))
            return
        fi
    fi

    # bulk-edit sub-subcommand
    if [ "$subcmd" = "bulk-edit" ]; then
        if [ $COMP_CWORD -eq 3 ]; then
            COMPREPLY=($(compgen -W "{bulk_edit_types}" -- "$cur"))
            return
        fi
        if [ $COMP_CWORD -gt 3 ]; then
            local bulk_sub="${{COMP_WORDS[3]}}"
            local opts=""
            case "$bulk_sub" in
{bulk_case_block}
            esac
            COMPREPLY=($(compgen -W "$opts" -- "$cur"))
            return
        fi
    fi

    # freq-tools sub-subcommand
    if [ "$subcmd" = "freq-tools" ]; then
        if [ $COMP_CWORD -eq 2 ]; then
            COMPREPLY=($(compgen -W "{freq_tools_types}" -- "$cur"))
            return
        fi
    fi

    # remove: type completion at position 3
    if [ "$subcmd" = "remove" ] && [ $COMP_CWORD -eq 3 ]; then
        COMPREPLY=($(compgen -W "{set_types}" -- "$cur"))
        return
    fi

    # list: type completion at position 3
    if [ "$subcmd" = "list" ] && [ $COMP_CWORD -eq 3 ]; then
        COMPREPLY=($(compgen -W "{list_types}" -- "$cur"))
        return
    fi

    # set-option: option path completion at position 3
    if [ "$subcmd" = "set-option" ] && [ $COMP_CWORD -eq 3 ]; then
        COMPREPLY=($(compgen -W "{option_paths} --list" -- "$cur"))
        return
    fi

    # File argument completion (position 2 for most commands)
    if [ $COMP_CWORD -eq 2 ]; then
        _filedir '@(PRS|prs|json|JSON|ini|INI)'
        return
    fi

    # Flag completion for the active subcommand
    if [[ "$cur" == -* ]]; then
        local opts=""
        case "$subcmd" in
{flag_case_block}
        esac
        COMPREPLY=($(compgen -W "$opts" -- "$cur"))
        return
    fi

    # Default: file completion
    _filedir '@(PRS|prs)'
}}
complete -F _quickprs_complete quickprs
complete -F _quickprs_complete QuickPRS
'''


def generate_powershell_completion():
    """Generate PowerShell tab completion script for the quickprs CLI.

    Returns the script as a string. Users install it with:
        quickprs --completion powershell | Invoke-Expression
    """
    subcommands_ps = ", ".join(f"'{s}'" for s in SUBCOMMANDS)
    inject_types_ps = ", ".join(f"'{s}'" for s in INJECT_TYPES)
    bulk_edit_types_ps = ", ".join(f"'{s}'" for s in BULK_EDIT_TYPES)
    freq_tools_types_ps = ", ".join(f"'{s}'" for s in FREQ_TOOLS_TYPES)
    templates_ps = ", ".join(f"'{s}'" for s in TEMPLATE_NAMES)
    scanner_fmts_ps = ", ".join(f"'{s}'" for s in SCANNER_FORMATS)
    set_types_ps = ", ".join(f"'{s}'" for s in SET_TYPES)
    list_types_ps = ", ".join(f"'{s}'" for s in LIST_TYPES)
    option_paths_ps = ", ".join(f"'{s}'" for s in OPTION_PATHS)

    # Build flag hashtable entries
    flag_entries = []
    for cmd, flags in _SUBCOMMAND_FLAGS.items():
        if flags:
            flags_ps = ", ".join(f"'{f}'" for f in flags)
            flag_entries.append(f"        '{cmd}' = @({flags_ps})")

    inject_entries = []
    for sub, flags in _INJECT_FLAGS.items():
        flags_ps = ", ".join(f"'{f}'" for f in flags)
        inject_entries.append(f"        '{sub}' = @({flags_ps})")

    bulk_entries = []
    for sub, flags in _BULK_EDIT_FLAGS.items():
        flags_ps = ", ".join(f"'{f}'" for f in flags)
        bulk_entries.append(f"        '{sub}' = @({flags_ps})")

    flag_block = "\n".join(flag_entries)
    inject_block = "\n".join(inject_entries)
    bulk_block = "\n".join(bulk_entries)

    return f'''# PowerShell completion for quickprs
# Install: quickprs --completion powershell | Invoke-Expression

Register-ArgumentCompleter -Native -CommandName @('quickprs', 'QuickPRS') -ScriptBlock {{
    param($wordToComplete, $commandAst, $cursorPosition)

    $commands = @({subcommands_ps})
    $injectTypes = @({inject_types_ps})
    $bulkEditTypes = @({bulk_edit_types_ps})
    $freqToolsTypes = @({freq_tools_types_ps})
    $templates = @({templates_ps})
    $scannerFormats = @({scanner_fmts_ps})
    $setTypes = @({set_types_ps})
    $listTypes = @({list_types_ps})
    $optionPaths = @({option_paths_ps})

    $subcmdFlags = @{{
{flag_block}
    }}

    $injectFlags = @{{
{inject_block}
    }}

    $bulkEditFlags = @{{
{bulk_block}
    }}

    $tokens = $commandAst.ToString().Split(' ', [StringSplitOptions]::RemoveEmptyEntries)
    $tokenCount = $tokens.Count

    # If the cursor is after a space (typing new token), add empty element
    $cmdText = $commandAst.ToString()
    if ($cmdText.Length -lt $cursorPosition) {{
        $tokenCount++
    }} elseif ($cmdText[$cursorPosition - 1] -eq ' ' -and $wordToComplete -eq '') {{
        $tokenCount++
    }}

    $prevToken = if ($tokenCount -ge 2) {{ $tokens[$tokenCount - 2] }} else {{ '' }}

    # Complete subcommand (position 1)
    if ($tokenCount -eq 2) {{
        $completions = $commands + @('--version', '--completion')
        $completions | Where-Object {{ $_ -like "$wordToComplete*" }} | ForEach-Object {{
            [System.Management.Automation.CompletionResult]::new($_, $_, 'ParameterValue', $_)
        }}
        return
    }}

    $subcmd = if ($tokens.Count -ge 2) {{ $tokens[1] }} else {{ '' }}

    # --completion value
    if ($prevToken -eq '--completion') {{
        @('bash', 'powershell') | Where-Object {{ $_ -like "$wordToComplete*" }} | ForEach-Object {{
            [System.Management.Automation.CompletionResult]::new($_, $_, 'ParameterValue', $_)
        }}
        return
    }}

    # --template value
    if ($prevToken -eq '--template') {{
        $templates | Where-Object {{ $_ -like "$wordToComplete*" }} | ForEach-Object {{
            [System.Management.Automation.CompletionResult]::new($_, $_, 'ParameterValue', $_)
        }}
        return
    }}

    # --format value
    if ($prevToken -eq '--format') {{
        $scannerFormats | Where-Object {{ $_ -like "$wordToComplete*" }} | ForEach-Object {{
            [System.Management.Automation.CompletionResult]::new($_, $_, 'ParameterValue', $_)
        }}
        return
    }}

    # inject sub-subcommand (position 3)
    if ($subcmd -eq 'inject' -and $tokenCount -eq 4) {{
        $injectTypes | Where-Object {{ $_ -like "$wordToComplete*" }} | ForEach-Object {{
            [System.Management.Automation.CompletionResult]::new($_, $_, 'ParameterValue', $_)
        }}
        return
    }}

    # inject flags (position 4+)
    if ($subcmd -eq 'inject' -and $tokenCount -gt 4 -and $tokens.Count -ge 4) {{
        $injectSub = $tokens[3]
        if ($injectFlags.ContainsKey($injectSub)) {{
            $injectFlags[$injectSub] | Where-Object {{ $_ -like "$wordToComplete*" }} | ForEach-Object {{
                [System.Management.Automation.CompletionResult]::new($_, $_, 'ParameterValue', $_)
            }}
        }}
        return
    }}

    # bulk-edit sub-subcommand (position 3)
    if ($subcmd -eq 'bulk-edit' -and $tokenCount -eq 4) {{
        $bulkEditTypes | Where-Object {{ $_ -like "$wordToComplete*" }} | ForEach-Object {{
            [System.Management.Automation.CompletionResult]::new($_, $_, 'ParameterValue', $_)
        }}
        return
    }}

    # bulk-edit flags (position 4+)
    if ($subcmd -eq 'bulk-edit' -and $tokenCount -gt 4 -and $tokens.Count -ge 4) {{
        $bulkSub = $tokens[3]
        if ($bulkEditFlags.ContainsKey($bulkSub)) {{
            $bulkEditFlags[$bulkSub] | Where-Object {{ $_ -like "$wordToComplete*" }} | ForEach-Object {{
                [System.Management.Automation.CompletionResult]::new($_, $_, 'ParameterValue', $_)
            }}
        }}
        return
    }}

    # freq-tools sub-subcommand (position 2)
    if ($subcmd -eq 'freq-tools' -and $tokenCount -eq 3) {{
        $freqToolsTypes | Where-Object {{ $_ -like "$wordToComplete*" }} | ForEach-Object {{
            [System.Management.Automation.CompletionResult]::new($_, $_, 'ParameterValue', $_)
        }}
        return
    }}

    # remove: type completion (position 3)
    if ($subcmd -eq 'remove' -and $tokenCount -eq 4) {{
        $setTypes | Where-Object {{ $_ -like "$wordToComplete*" }} | ForEach-Object {{
            [System.Management.Automation.CompletionResult]::new($_, $_, 'ParameterValue', $_)
        }}
        return
    }}

    # list: type completion (position 3)
    if ($subcmd -eq 'list' -and $tokenCount -eq 4) {{
        $listTypes | Where-Object {{ $_ -like "$wordToComplete*" }} | ForEach-Object {{
            [System.Management.Automation.CompletionResult]::new($_, $_, 'ParameterValue', $_)
        }}
        return
    }}

    # set-option: option path completion (position 3)
    if ($subcmd -eq 'set-option' -and $tokenCount -eq 4) {{
        $completions = $optionPaths + @('--list')
        $completions | Where-Object {{ $_ -like "$wordToComplete*" }} | ForEach-Object {{
            [System.Management.Automation.CompletionResult]::new($_, $_, 'ParameterValue', $_)
        }}
        return
    }}

    # Flag completion for the active subcommand
    if ($wordToComplete -like '-*' -and $subcmdFlags.ContainsKey($subcmd)) {{
        $subcmdFlags[$subcmd] | Where-Object {{ $_ -like "$wordToComplete*" }} | ForEach-Object {{
            [System.Management.Automation.CompletionResult]::new($_, $_, 'ParameterValue', $_)
        }}
        return
    }}

    # Default: PRS file completion
    Get-ChildItem -Path "$wordToComplete*" -Include '*.PRS', '*.prs' -ErrorAction SilentlyContinue | ForEach-Object {{
        [System.Management.Automation.CompletionResult]::new($_.Name, $_.Name, 'ProviderItem', $_.FullName)
    }}
}}
'''
