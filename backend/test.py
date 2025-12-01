from orchestration import run_agent
import time
def mk_msg(text):
    return [{"role":"user","parts":[{"text": text}]}]
def run_sim():
    sid = "test-session-1"
    steps = [
        "hello",
        "i want to book an agent",
        "my name is Aarush Verma",
        "+91 9876543210",
        "December 10",
        "7 pm",
        "restaurant",
        "I want web integration and whatsapp_integration",
        "confirm",
        "generate qr"
    ]
    for s in steps:
        print("USER >", s)
        out = run_agent(mk_msg(s), sid)
        print("AGENT >", out)
        time.sleep(0.6)
if __name__ == "__main__":
    run_sim()