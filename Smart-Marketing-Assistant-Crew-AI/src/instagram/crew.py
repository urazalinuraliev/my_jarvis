from crewai import Agent, Crew, Process, Task
from crewai.project import CrewBase, agent, crew, task

from crew_llm import build_llm

# Every task that writes a file uses the {output_dir} input, so each run gets
# its own directory instead of overwriting files in the working directory.
# Pass output_dir alongside the other inputs, e.g. kickoff(inputs={..., "output_dir": "runs/today"}).


@CrewBase
class InstagramCrew():
    """Instagram crew"""
    agents_config = "config/agents.yaml"
    tasks_config = "config/tasks.yaml"

    @agent
    def market_researcher(self) -> Agent:
        return Agent(
            config=self.agents_config['market_researcher'],
            tools=[],
            verbose=True,
            llm=build_llm(),
        )

    @agent
    def content_strategist(self) -> Agent:
        return Agent(config=self.agents_config["content_strategist"], verbose=True, llm=build_llm())

    @agent
    def visual_creator(self) -> Agent:
        return Agent(
            config=self.agents_config["visual_creator"],
            verbose=True,
            allow_delegation=False,
            llm=build_llm(),
        )

    @agent
    def copywriter(self) -> Agent:
        return Agent(config=self.agents_config["copywriter"], verbose=True, llm=build_llm())


    @task
    def market_research(self) -> Task:
        return Task(
            config=self.tasks_config["market_research"],
            agent=self.market_researcher(),
            output_file="{output_dir}/market_research.md",
        )

    @task
    def content_strategy_task(self) -> Task:
        return Task(
            config=self.tasks_config["content_strategy"],
            agent=self.content_strategist(),
        )

    @task
    def visual_content_creation_task(self) -> Task:
        return Task(
            config=self.tasks_config["visual_content_creation"],
            agent=self.visual_creator(),
            output_file="{output_dir}/visual-content.md",
        )

    @task
    def copywriting_task(self) -> Task:
        return Task(
            config=self.tasks_config["copywriting"],
            agent=self.copywriter(),
        )

    @task
    def report_final_content_strategy(self) -> Task:
        return Task(
            config=self.tasks_config["report_final_content_strategy"],
            agent=self.content_strategist(),
            output_file="{output_dir}/final-content-strategy.md",
        )

    @crew
    def crew(self) -> Crew:
        """Creates the Instagram crew"""
        return Crew(
            agents=self.agents,  # Automatically created by the @agent decorator
            tasks=self.tasks,  # Automatically created by the @task decorator
            process=Process.sequential,
            verbose=True,
            # process=Process.hierarchical, # In case you wanna use that instead https://docs.crewai.com/how-to/Hierarchical/
        )
