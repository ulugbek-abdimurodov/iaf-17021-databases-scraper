$ErrorActionPreference = "Stop"

function Test-PortAvailable {
  param([int]$Port)

  $listener = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue
  if ($listener) {
    $owners = $listener | Select-Object -ExpandProperty OwningProcess -Unique
    $processNames = $owners | ForEach-Object {
      (Get-Process -Id $_ -ErrorAction SilentlyContinue).ProcessName
    }
    $names = ($processNames -join ", ")
    Write-Error "Port $Port is already in use$(if ($names) { " by $names" })."
  }
}

if (-not (Get-Command docker -ErrorAction SilentlyContinue)) {
  Write-Error "Docker is required but was not found on PATH."
}

Write-Host "Starting certifind-postgres with Docker Compose..."
docker compose up -d postgres
if ($LASTEXITCODE -ne 0) {
  Write-Error "Docker Compose could not start certifind-postgres."
}

Test-PortAvailable -Port 8080
Test-PortAvailable -Port 3000

Write-Host ""
Write-Host "Development services are ready:"
Write-Host "  PostgreSQL: certifind-postgres (Docker Compose)"
Write-Host "  Backend:    run your backend command on http://localhost:8080"
Write-Host "  Frontend:   npm run dev (http://localhost:3000)"
Write-Host ""
Write-Host "Run the backend first, then start the frontend in a separate terminal."
Write-Host "On a new database volume, load the company data first (see README, 'Start locally'):"
Write-Host '  cd backend; .\mvnw.cmd spring-boot:run "-Dspring-boot.run.profiles=import" "-Dspring-boot.run.arguments=--certifind.import.paths=../data"'
