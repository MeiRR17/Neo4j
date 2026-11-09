# Legacy Windows entry point. Uses local-only, authenticated smoke instead.
$script = Join-Path $PSScriptRoot "smoke.py"
python $script
exit $LASTEXITCODE
