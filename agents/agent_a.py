from langchain.chat_models import init_chat_model

class TaskSource:
    def get_task(self) -> str:
        raise NotImplementedError

class ConsoleSource(TaskSource):
    def get_task(self) -> str:
        question = input("\nDescribe task & mention the app ('exit' to quit): ").strip()
        if question.lower() in ("exit", "quit"):
            return None
        return question
    
class APISource(TaskSource):
    def get_task(self) -> str:
        raise NotImplementedError("APISource will handle tasks coming from the web API in a future version.")

class Command_AgentA:
    def __init__(
            self, 
            source: TaskSource, 
            name = "Agent A", 
            model_name = "openai:gpt-4.1-mini"
        ):
        self.name = name
        self.source = source

        # Agent A's own LLM for rewriting/simplifying user input
        self.llm = init_chat_model(model_name)

        self.system_prompt = (
            """
            You rewrite messy or long user input into ONE clear, concise,
            single-sentence task that tells an automation agent exactly what to do.
            Rules:
            1. Extract the user's main intent.
            2. Rewrite it as ONE short, direct sentence.
            3. Do not add details that were not provided.
            4. Output only the final rewritten task.
            """
        )

    def normalize_question(self, raw_question: str) -> str:
        """Use the LLM to rewrite the question."""
        response = self.llm.invoke([
            {"role": "system", "content": self.system_prompt},
            {"role": "user", "content": raw_question}
        ])
        return response.content.strip()   

    def generate_task(self):
        """Returns a clean one-line task, or None if exiting."""
        raw_question = self.source.get_task()
        if raw_question is None:
            return None  
        
        question = self.normalize_question(raw_question)
        print(f"[TASK] {self.name} simplified task: {question}")
        
        return question