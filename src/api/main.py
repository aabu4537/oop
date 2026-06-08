from fastapi import FastAPI

from src.api.routers import matches, players, predictions, simulation, teams

app = FastAPI(title="Football Analytics API", version="1.0.0")

app.include_router(teams.router)
app.include_router(matches.router)
app.include_router(predictions.router)
app.include_router(players.router)
app.include_router(simulation.router)


@app.get("/health")
def health():
    return {"status": "ok"}
