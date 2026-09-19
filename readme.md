# Smart Marketing Assistant using Crew AI

## Overview
The Smart Marketing Assistant is an innovative project that leverages AI agents to automate tasks within an Instagram marketing workflow. This project aims to streamline and optimize various marketing activities, providing users with a powerful tool to enhance their social media strategies.

## Workflow
![](https://github.com/praj2408/Smart-Marketing-Assistant-using-Ai-Agents/blob/main/docs/crew2-instagram.jpg)
## Features
- **Automated Content Creation**: Generate engaging posts and stories using AI-powered content creation tools.
- **Hashtag Optimization**: Analyze and suggest the most effective hashtags to reach a wider audience.
- **X Trend Research**: Search recent public X posts for competitor mentions, hashtags, and campaign signals.
- **Post Scheduling**: Automatically schedule posts at optimal times for maximum engagement.
- **Performance Analytics**: Track and analyze the performance of posts and campaigns.
- **Audience Interaction**: Automate responses to comments and messages to maintain active engagement with followers.

## Installation

1. Clone the repository:
   ```bash
   git clone https://github.com/yourusername/Smart-Marketing-Assistant-using-Ai-Agents.git
   cd Smart-Marketing-Assistant-using-Ai-Agents
   ```

2. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```

3. Set up environment variables:
   - Create a `.env` file in the root directory.
   - Add the following variables:
     ```
     ANTHROPIC_API_KEY=your anthropic api key
     # Optional; this is the default model:
     CREWAI_MODEL=anthropic/claude-sonnet-5
     # Optional; meeting-prep web search and X trend search:
     EXA_API_KEY=your exa api key
     XQUIK_API_KEY=your xquik api key
     ```

## Usage

1. **Run the Assistant**:
   ```bash
   python main.py
   ```

2. **Access the Dashboard**:
   Open your web browser and navigate to `http://localhost:5000` to access the Smart Marketing Assistant dashboard.

## Configuration

- **Customization**:
  You can customize the assistant's behavior and settings by modifying the `config.py` file.

- **AI Models**:
  Every agent gets its model from `src/crew_llm.py`, which reads `CREWAI_MODEL` (default `anthropic/claude-sonnet-5`).

- **Optional X Search**:
  If `XQUIK_API_KEY` is set, the CrewAI research agents can call `search_x_posts` to gather recent public X posts for trend, hashtag, and competitor research. Without the key, the tool returns setup guidance and the existing Exa tools continue to work.

## Project Structure
- `requirements.txt:` Lists required Python dependencies.
- `main.py:` Main script to run the AI agents.
- `agents:` (Optional) Folder containing code for individual AI agents (market research, content strategy, etc.)
- `config.py:` (Optional) Configuration file for Crew AI project and API key.

## Contributing

We welcome contributions to enhance the functionality of the Smart Marketing Assistant. To contribute:

1. Fork the repository.
2. Create a new branch:
   ```bash
   git checkout -b feature-branch
   ```
3. Make your changes and commit them:
   ```bash
   git commit -m "Add new feature"
   ```
4. Push to the branch:
   ```bash
   git push origin feature-branch
   ```
5. Create a pull request.

## License

This project is licensed under the MIT License.

## Contact

For any inquiries or support, please open an issue in the repository or contact the project maintainers.

---

Thank you for using the Smart Marketing Assistant! We hope it helps you achieve your Instagram marketing goals.
