from crewai_tools import SerperDevTool

class SearchTools:
    @staticmethod
    def search_internet(query: str):
        """Search the internet for a given query."""
        tool = SerperDevTool()
        return tool.run(query)