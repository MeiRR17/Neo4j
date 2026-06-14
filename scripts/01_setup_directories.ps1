# Script 01 - Create required local directories for Neo4j volume mounts
# Run this BEFORE starting the Docker container

Write-Host "Creating Neo4j local directories..." -ForegroundColor Cyan

$dirs = @("C:\neo4j\data", "C:\neo4j\import", "C:\neo4j\logs")

foreach ($dir in $dirs) {
    if (-not (Test-Path $dir)) {
        New-Item -ItemType Directory -Path $dir -Force | Out-Null
        Write-Host "  Created: $dir" -ForegroundColor Green
    } else {
        Write-Host "  Already exists: $dir" -ForegroundColor Yellow
    }
}

Write-Host "`nDirectories ready. Now run:" -ForegroundColor Cyan
Write-Host "  docker run --name neo4j-project10 -p 7474:7474 -p 7687:7687 -d ``" -ForegroundColor White
Write-Host "    -v C:\neo4j\data:/data ``" -ForegroundColor White
Write-Host "    -v C:\neo4j\import:/var/lib/neo4j/import ``" -ForegroundColor White
Write-Host "    -v C:\neo4j\logs:/logs ``" -ForegroundColor White
Write-Host "    -e NEO4J_AUTH=neo4j/password ``" -ForegroundColor White
Write-Host "    -e NEO4J_PLUGINS=[`"apoc`"] ``" -ForegroundColor White
Write-Host "    -e NEO4J_dbms_memory_heap_max__size=4G ``" -ForegroundColor White
Write-Host "    neo4j:latest" -ForegroundColor White
Write-Host "`nOR simply run:  docker-compose up -d" -ForegroundColor Cyan
