# Legacy Windows entry point. Local paths and demo docker run are deprecated.
$script = Join-Path $PSScriptRoot "bootstrap.py"
python $script
exit $LASTEXITCODE
