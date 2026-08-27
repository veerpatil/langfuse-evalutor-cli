LLM_AS_JUDGE_EVALUATORS = [
    {
        "name": "Product Version Accuracy",
        "description": "Checks if the response references the correct product version",
        "type": "llm_as_judge",
        "prompt": (
            "You are evaluating a support assistant response.\n\n"
            "User question:\n{{input}}\n\n"
            "Assistant response:\n{{output}}\n\n"
            "Expected product version context:\n{{ground_truth}}\n\n"
            "Does the assistant response reference the correct product version? "
            "Answer true if the version is correct or if no specific version claim is made. "
            "Answer false if the response mentions an incorrect version."
        ),
        "outputDefinition": {
            "dataType": "BOOLEAN",
            "reasoning": {
                "description": "Explain why the version reference is correct or incorrect"
            },
            "score": {
                "description": "true if version is accurate, false otherwise"
            },
        },
    },
    {
        "name": "Response Relevance",
        "description": "Checks if the response is relevant to the user question",
        "type": "llm_as_judge",
        "prompt": (
            "You are evaluating a support assistant response.\n\n"
            "User question:\n{{input}}\n\n"
            "Assistant response:\n{{output}}\n\n"
            "Is the assistant response relevant to the user's question? "
            "Answer true if the response directly addresses the question. "
            "Answer false if the response is off-topic or does not answer what was asked."
        ),
        "outputDefinition": {
            "dataType": "BOOLEAN",
            "reasoning": {
                "description": "Explain why the response is or is not relevant"
            },
            "score": {
                "description": "true if relevant, false otherwise"
            },
        },
    },
    {
        "name": "Factual Correctness",
        "description": "Checks if the response contains factually correct information",
        "type": "llm_as_judge",
        "prompt": (
            "You are evaluating a support assistant response.\n\n"
            "User question:\n{{input}}\n\n"
            "Assistant response:\n{{output}}\n\n"
            "Expected correct information:\n{{ground_truth}}\n\n"
            "Does the assistant response contain factually correct information "
            "consistent with the ground truth? Answer true if the facts are accurate. "
            "Answer false if there are factual errors."
        ),
        "outputDefinition": {
            "dataType": "BOOLEAN",
            "reasoning": {
                "description": "Explain which facts are correct or incorrect"
            },
            "score": {
                "description": "true if factually correct, false otherwise"
            },
        },
    },
    {
        "name": "Response Completeness",
        "description": "Checks if the response fully addresses all parts of the user question",
        "type": "llm_as_judge",
        "prompt": (
            "You are evaluating a support assistant response.\n\n"
            "User question:\n{{input}}\n\n"
            "Assistant response:\n{{output}}\n\n"
            "Expected complete answer:\n{{ground_truth}}\n\n"
            "Does the assistant response fully address all parts of the user's question? "
            "Answer true if the response is complete. "
            "Answer false if it misses important aspects of the question."
        ),
        "outputDefinition": {
            "dataType": "BOOLEAN",
            "reasoning": {
                "description": "Explain what parts were addressed or missed"
            },
            "score": {
                "description": "true if complete, false otherwise"
            },
        },
    },
]
