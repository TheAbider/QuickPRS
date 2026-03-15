"""CLI cheat sheet — comprehensive quick-reference for all commands."""


def generate_cheat_sheet():
    """Generate a formatted CLI cheat sheet."""
    return """\
QuickPRS CLI Cheat Sheet
========================

GETTING STARTED
  quickprs wizard                           Interactive guided setup
  quickprs create radio.PRS                 Create blank personality
  quickprs build config.ini -o radio.PRS    Build from config file
  quickprs profiles build scanner_basic     Build from profile template

ADD CONTENT
  quickprs inject radio.PRS p25 --name SYS --sysid 892 --freqs-csv f.csv --tgs-csv t.csv
  quickprs inject radio.PRS conv --template murs
  quickprs inject radio.PRS conv --template noaa
  quickprs inject radio.PRS conv --template interop
  quickprs inject radio.PRS conv --channels-csv ch.csv
  quickprs inject radio.PRS talkgroups --set "SYS" --tgs-csv tgs.csv
  quickprs systems add radio.PRS PSERN      Add from built-in database

IMPORT
  quickprs import-rr radio.PRS --sid 8155 --username X --apikey Y
  quickprs import-paste radio.PRS --name SYS --sysid 892 --tgs-file tgs.txt
  quickprs import-scanner radio.PRS --csv channels.csv
  quickprs import-json config.json -o radio.PRS

MODIFY
  quickprs edit radio.PRS --name "NEW NAME"
  quickprs rename radio.PRS --set "SYS" --pattern "OLD" --replace "NEW"
  quickprs sort radio.PRS --set "SYS" --key name --type group
  quickprs bulk-edit radio.PRS talkgroups --set "SYS" --enable-tx
  quickprs renumber radio.PRS --set "MURS" --start 1
  quickprs encrypt radio.PRS --set "SYS" --all --key-id 1
  quickprs set-option radio.PRS gps.gpsMode ON
  quickprs remove radio.PRS system "SYSTEM NAME"
  quickprs merge radio.PRS source.PRS --all
  quickprs clone radio.PRS source.PRS "SYSTEM NAME"

INSPECT
  quickprs info radio.PRS --detail
  quickprs validate radio.PRS
  quickprs health radio.PRS
  quickprs suggest radio.PRS
  quickprs capacity radio.PRS
  quickprs stats radio.PRS
  quickprs list radio.PRS talkgroups
  quickprs freq-map radio.PRS
  quickprs compare a.PRS b.PRS --detail
  quickprs search *.PRS --freq 851.0125

EXPORT
  quickprs export-json radio.PRS
  quickprs export-csv radio.PRS output_dir/
  quickprs export-config radio.PRS -o config.ini
  quickprs export radio.PRS chirp -o channels.csv
  quickprs report radio.PRS -o report.html
  quickprs card radio.PRS -o card.html

FLEET
  quickprs fleet config.ini --units units.csv -o fleet_dir/
  quickprs fleet-check radio1.PRS radio2.PRS radio3.PRS
  quickprs snapshot radio.PRS -o snapshot.json

MAINTENANCE
  quickprs backup radio.PRS --list
  quickprs backup radio.PRS --restore
  quickprs cleanup radio.PRS --check
  quickprs repair radio.PRS -o fixed.PRS
  quickprs watch radio.PRS

REFERENCE
  quickprs freq-tools tones
  quickprs freq-tools offset 146.94
  quickprs freq-tools identify 462.5625
  quickprs template-csv frequencies -o template.csv
  quickprs cheat-sheet
  quickprs --completion bash"""
