from langchain_openai import ChatOpenAI
from langchain_core.messages import SystemMessage, HumanMessage
import nouse

# 1. Initialize NoUse memory
# NoUse acts as a persistent domain memory/context injector.
brain = nouse.attach()

# 2. Initialize the LLM
llm = ChatOpenAI(model="gpt-4.1-mini")

# 3. Define the query
question = "Explain the relationship between attention and memory in transformers."

# 4. Inject Context
# Here, NoUse retrieves relevant domain knowledge to ground the LLM's response.
context = brain.query(question).context_block()

messages = [
    SystemMessage(content=f"You are a helpful assistant. Use the following context to answer: {context}"),
    HumanMessage(content=question),
]

# 5. Invoke the chain
response = llm.invoke(messages)

print(f"--- Question ---\n{question}\n")
print(f"--- Response ---\n{response.content}")