from agents.agent_a import Command_AgentA, ConsoleSource
from agents.agent_b import Navigator_AgentB


def main():
    # Create both agents
    agent_a = Command_AgentA(ConsoleSource())
    agent_b = Navigator_AgentB()

    while True:
        task = agent_a.generate_task()
        if task is None:
            print("[INFO] No task received, shutting down\n")
            break
        agent_b.handle_question(task)

if __name__ == "__main__":
    main()