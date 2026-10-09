"""Food search: a small HTML piece the carbs page loads into itself (HTMX)."""

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse

from glucobalance.foods import FoodSearchError, clean_query
from glucobalance.web.deps import CurrentUser, FoodSources, Templates
from glucobalance.web.rendering import render

router = APIRouter(prefix="/log")


@router.get("/foods", response_class=HTMLResponse)
def search_foods(
    request: Request, user: CurrentUser, templates: Templates, foods: FoodSources, q: str = ""
) -> HTMLResponse:
    results = []
    message = None
    try:
        results = foods.search(clean_query(q))
        if not results:
            message = "No foods found. Try another word, or enter the carbs by hand."
    except FoodSearchError as problem:
        message = str(problem)
    return render(
        request, templates, "log/_food_results.html", user, foods=results, message=message
    )
