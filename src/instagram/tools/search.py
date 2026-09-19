class SearchTools:
    @staticmethod
    def search_internet(query: str):
        """Search the internet for a given query (needs crewai-tools and SERPER_API_KEY)."""
        # Imported lazily: crewai-tools is an optional, heavy dependency, and
        # importing it at module load would break the crew for anyone who
        # doesn't use this helper.
        from crewai_tools import SerperDevTool

        tool = SerperDevTool()
        return tool.run(query)
