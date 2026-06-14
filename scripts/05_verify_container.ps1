# Script 05 - Verify Docker container is running and Neo4j is reachable

Write-Host "=== Neo4j Container Health Check ===" -ForegroundColor Cyan

# Check Docker is running
try {
    $dockerInfo = docker info 2>&1
    if ($LASTEXITCODE -ne 0) { throw "Docker not running" }
    Write-Host "[OK] Docker engine is running" -ForegroundColor Green
} catch {
    Write-Host "[FAIL] Docker is not running. Please start Docker Desktop." -ForegroundColor Red
    exit 1
}

# Check container status
$container = docker ps --filter "name=neo4j-project10" --format "{{.Status}}" 2>&1
if ($container -like "Up*") {
    Write-Host "[OK] Container neo4j-project10 is: $container" -ForegroundColor Green
} else {
    Write-Host "[WARN] Container not running. Starting..." -ForegroundColor Yellow
    docker start neo4j-project10 2>&1
    Start-Sleep -Seconds 10
}

# Wait for Neo4j HTTP endpoint
Write-Host "Waiting for Neo4j Browser to become available..." -ForegroundColor Cyan
$maxRetries = 12
$retries = 0
$ready = $false

while ($retries -lt $maxRetries -and -not $ready) {
    try {
        $response = Invoke-WebRequest -Uri "http://localhost:7474" -TimeoutSec 3 -ErrorAction Stop
        if ($response.StatusCode -eq 200) {
            $ready = $true
        }
    } catch {
        $retries++
        Write-Host "  Attempt $retries/$maxRetries - not ready yet..." -ForegroundColor Yellow
        Start-Sleep -Seconds 5
    }
}

if ($ready) {
    Write-Host "[OK] Neo4j Browser is live at http://localhost:7474" -ForegroundColor Green
    Write-Host "     Username: neo4j | Password: password" -ForegroundColor White
    Start-Process "http://localhost:7474"
} else {
    Write-Host "[FAIL] Neo4j did not become ready. Check docker logs:" -ForegroundColor Red
    Write-Host "       docker logs neo4j-project10" -ForegroundColor White
}

# Check import file
if (Test-Path "C:\neo4j\import\sefaria_links.csv") {
    $lines = (Get-Content "C:\neo4j\import\sefaria_links.csv" | Measure-Object -Line).Lines
    Write-Host "[OK] sefaria_links.csv found with $lines rows" -ForegroundColor Green
} else {
    Write-Host "[WARN] sefaria_links.csv not found in C:\neo4j\import\" -ForegroundColor Yellow
    Write-Host "       Run: python scripts\02_acquire_sefaria_data.py" -ForegroundColor White
}
