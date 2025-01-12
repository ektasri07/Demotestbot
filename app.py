import os
from botbuilder.core import ActivityHandler, MessageFactory, TurnContext
from botbuilder.schema import Activity, ChannelAccount
import pandas as pd
from azure.identity import DefaultAzureCredential
import requests
from datetime import datetime
import openai

class AzureCostBot(ActivityHandler):
    def __init__(self):
        super().__init__()
        openai.api_key = os.getenv('OPENAI_API_KEY')
        openai.api_base = os.getenv('OPENAI_ENDPOINT_URL')
        self.microsoft_app_id = os.getenv('MicrosoftAppId')
        self.microsoft_app_password = os.getenv('MicrosoftAppPassword')

    async def on_members_added_activity(self, members_added: [ChannelAccount], turn_context: TurnContext):
        for member in members_added:
            if member.id != turn_context.activity.recipient.id:
                await turn_context.send_activity("Welcome to the Azure Subscription Cost Chatbot! Ask me about Azure costs.")

    async def on_message_activity(self, turn_context: TurnContext):
        user_input = turn_context.activity.text
        try:
            start_date_str, end_date_str = user_input.split(" to ")
            start_date = datetime.strptime(start_date_str.strip(), '%Y-%m-%d')
            end_date = datetime.strptime(end_date_str.strip(), '%Y-%m-%d')

            cost_data = self.get_cost_data(start_date, end_date)

            # Extract relevant data and create a DataFrame
            data = []
            for item in cost_data['properties']['rows']:
                data.append({
                    'Resource Group': item[2],
                    'Date': item[1],
                    'Cost': item[0]
                })

            df = pd.DataFrame(data)

            # Get a response from OpenAI API
            prompt = f"User asked about Azure costs from {start_date_str} to {end_date_str}. Here's the data:\n{df.to_string()}\nSummarize the costs."
            ai_response = self.get_openai_response(prompt)

            await turn_context.send_activity(MessageFactory.text(ai_response))
        except ValueError:
            await turn_context.send_activity("Please enter dates in the format 'YYYY-MM-DD to YYYY-MM-DD'.")

    def get_cost_data(self, start_date, end_date):
        credential = DefaultAzureCredential()
        subscription_id = os.getenv('SUBSCRIPTION_ID')
        cost_management_url = f"https://management.azure.com/subscriptions/{subscription_id}/providers/Microsoft.CostManagement/query?api-version=2021-10-01"

        headers = {
            'Authorization': f'Bearer {credential.get_token("https://management.azure.com/.default").token}',
            'Content-Type': 'application/json'
        }

        start_date_str = start_date.strftime('%Y-%m-%d')
        end_date_str = end_date.strftime('%Y-%m-%d')

        query = {
            "type": "Usage",
            "timeframe": "Custom",
            "timePeriod": {
                "from": start_date_str,
                "to": end_date_str
            },
            "dataset": {
                "granularity": "Daily",
                "aggregation": {
                    "totalCost": {
                        "name": "Cost",
                        "function": "Sum"
                    }
                },
                "grouping": [
                    {
                        "type": "Dimension",
                        "name": "ResourceGroupName"
                    }
                ]
            }
        }

        response = requests.post(cost_management_url, headers=headers, json=query)
        response.raise_for_status()
        return response.json()

    def get_openai_response(self, prompt):
        response = openai.Completion.create(
            engine="davinci-codex",
            prompt=prompt,
            max_tokens=150
        )
        return response.choices[0].text.strip()

if __name__ == "__main__":
    from botbuilder.core import BotFrameworkAdapter, BotFrameworkAdapterSettings
    from botbuilder.integration.aiohttp import BotFrameworkHttpClient, BotFrameworkHttpAdapter
    from aiohttp import web

    settings = BotFrameworkAdapterSettings(os.getenv('MicrosoftAppId'), os.getenv('MicrosoftAppPassword'))
    adapter = BotFrameworkHttpAdapter(settings)

    bot = AzureCostBot()

    async def messages(req):
        body = await req.json()
        activity = Activity().deserialize(body)
        auth_header = req.headers.get("Authorization", "")
        response = await adapter.process_activity(activity, auth_header, bot.on_turn)
        return web.json_response(data=response.body, status=response.status)

    app = web.Application()
    app.router.add_post("/api/messages", messages)

    web.run_app(app, host="0.0.0.0", port=8000)