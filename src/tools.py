import os
from json import loads
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from exa_py import Exa
from langchain.agents import tool


XQUIK_SEARCH_URL = "https://xquik.com/api/v1/x/tweets/search"


def _as_text(value):
    if value is None:
        return ""
    return " ".join(str(value).split())


def _bounded_limit(value):
    try:
        parsed = int(float(value))
    except (TypeError, ValueError, OverflowError):
        return 5
    return max(1, min(parsed, 10))


def _tweet_records(payload):
    if isinstance(payload, list):
        return payload
    if not isinstance(payload, dict):
        return []
    for key in ("tweets", "results", "items"):
        value = payload.get(key)
        if isinstance(value, list):
            return value
    data = payload.get("data")
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        return _tweet_records(data)
    return []


def _tweet_line(tweet):
    if not isinstance(tweet, dict):
        return _as_text(tweet)
    author = tweet.get("author") or tweet.get("user") or {}
    if not isinstance(author, dict):
        author = {}
    username = _as_text(
        tweet.get("author_username")
        or tweet.get("username")
        or author.get("username")
        or author.get("screen_name")
        or author.get("handle")
    )
    text = _as_text(tweet.get("text") or tweet.get("full_text") or tweet.get("content"))
    tweet_id = _as_text(tweet.get("id") or tweet.get("tweet_id") or tweet.get("tweetId"))
    prefix = f"@{username}: " if username else ""
    suffix = f" ({tweet_id})" if tweet_id else ""
    return f"{prefix}{text}{suffix}".strip()


class XquikSearchToolSet():

    @tool
    def search_x_posts(query: str, limit: int = 5):
        """Search recent public X posts for trend, hashtag, and competitor research."""
        api_key = os.environ.get("XQUIK_API_KEY")
        if not api_key:
            return "Set XQUIK_API_KEY before using search_x_posts."
        query_text = _as_text(query)
        if not query_text:
            return "Provide a non-empty query before using search_x_posts."
        params = urlencode({
            "q": query_text,
            "limit": _bounded_limit(limit),
            "queryType": "Latest",
        })
        request = Request(
            f"{XQUIK_SEARCH_URL}?{params}",
            headers={
                "Authorization": f"Bearer {api_key}",
                "Accept": "application/json",
                "User-Agent": "smart-marketing-assistant-crewai",
            },
        )
        try:
            with urlopen(request, timeout=20) as response:
                payload = loads(response.read().decode("utf-8"))
        except HTTPError as error:
            return f"X search failed with HTTP {error.code}."
        except (OSError, URLError, ValueError) as error:
            return f"X search failed: {error.__class__.__name__}."
        lines = [_tweet_line(tweet) for tweet in _tweet_records(payload)]
        lines = [line for line in lines if line]
        if not lines:
            return "No recent X posts found for that query."
        return "\n".join(lines)

    def tools():
        return [
            XquikSearchToolSet.search_x_posts,
        ]

class ExaSearchToolSet():
    
    @tool
    def search(query:str):
        """Search for a webpage based on the query.
        
        Args:
            query (str): The search query string.
        
        Returns:
            list: A list of search results.
        """
        return ExaSearchToolSet._exa().search(f"{query}", use_autoprompt=True, num_results=3)
    
    @tool
    def find_similar(url: str):
        """Search for webpages similar to a given URL.
        
        The URL passed in should be a URL returned from 'search'.
        
        Args:
            url (str): The URL to find similar pages for.
        
        Returns:
            list: A list of similar search results.
        """
        return ExaSearchToolSet._exa().find_similar(url, num_results=3)
    
    @tool
    def get_contents(ids: str):
        """Get the contents of a webpage.
        
        The ids must be passed in as a list, a list of ids returned from 'search'.
        
        Args:
            ids (str): The IDs of the search results to get contents for.
        
        Returns:
            str: The content of the webpages concatenated and truncated to 1000 characters each.
        """
        # print("ids from params:",ids)
        # Evaluate the string representation of the list of IDs
        ids = eval(ids)
        # print("eval ids:",ids)
        
        # Get the contents of the webpages
        contents = str(ExaSearchToolSet._exa().get_contents(ids))
        print("contents:",contents)

        # Split the contents by 'URL:' and truncate each content to 1000 characters
        contents = contents.split("URL:")
        contents= [content[:1000] for content in contents]
        return "\n\n".join(contents)
    
    def tools():
        return [
            ExaSearchToolSet.search,
            ExaSearchToolSet.find_similar,
            ExaSearchToolSet.get_contents,
            *XquikSearchToolSet.tools(),
        ]

    def _exa():
        """Initialize and return an instance of the Exa class.
        
        Returns:
            Exa: An instance of the Exa class initialized with the API key from environment variables.
        """
        return Exa(api_key=os.environ.get('EXA_API_KEY'))
