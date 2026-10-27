from src.skills.insights_generation.main import create_agent


def create_insights_generation_agent(
    comparing_principles: str, model, working_dir: str = ".", debug: bool = False
):
    return create_agent(
        model=model,
        comparing_principles=comparing_principles,
        working_dir=working_dir,
        debug=debug,
    )
