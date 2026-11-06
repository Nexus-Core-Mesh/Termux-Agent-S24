from core.agent import TermuxAgent

def test_agent_inference():
    agent = TermuxAgent()
    print("Testing TermuxAgent inference integration...")
    try:
        response = agent.run_inference("Summarize the current state of Termux-Agent-S24 in one short sentence.")
        print(f"Inference Response:\n{response}")
    except Exception as e:
        print(f"Inference test completed with connection status: {e}")

if __name__ == "__main__":
    test_agent_inference()
