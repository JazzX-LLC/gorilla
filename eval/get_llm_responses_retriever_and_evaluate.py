# Copyright 2023 https://github.com/ShishirPatil/gorilla
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#    http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
import subprocess
import json
import argparse
import re
import os 
import sys
import json
import openai
import anthropic
import multiprocessing as mp
import time
import wandb
from tenacity import retry, wait_exponential
import sys
sys.path.append("/workspaces/gorilla/eval/eval-scripts")
sys.path.append("/workspaces/gorilla/")
sys.path.append("/workspaces/gorilla/data")
sys.path.append("/workspaces/gorilla/eval")
sys.path.append("/workspaces/gorilla/eval/eval-scripts")
sys.path.append("/workspaces/gorilla/eval/eval-data")



from importlib import import_module
class Args:
    pass
def encode_question(question, api_name):
    """Encode multiple prompt instructions into a single string."""
    
    prompts = []
    if api_name == "torchhub":
        domains = "1. $DOMAIN is inferred from the task description and should include one of {Classification, Semantic Segmentation, Object Detection, Audio Separation, Video Classification, Text-to-Speech}."
    elif api_name == "huggingface":
        domains = "1. $DOMAIN should include one of {Multimodal Feature Extraction, Multimodal Text-to-Image, Multimodal Image-to-Text, Multimodal Text-to-Video, \
        Multimodal Visual Question Answering, Multimodal Document Question Answer, Multimodal Graph Machine Learning, Computer Vision Depth Estimation,\
        Computer Vision Image Classification, Computer Vision Object Detection, Computer Vision Image Segmentation, Computer Vision Image-to-Image, \
        Computer Vision Unconditional Image Generation, Computer Vision Video Classification, Computer Vision Zero-Shor Image Classification, \
        Natural Language Processing Text Classification, Natural Language Processing Token Classification, Natural Language Processing Table Question Answering, \
        Natural Language Processing Question Answering, Natural Language Processing Zero-Shot Classification, Natural Language Processing Translation, \
        Natural Language Processing Summarization, Natural Language Processing Conversational, Natural Language Processing Text Generation, Natural Language Processing Fill-Mask,\
        Natural Language Processing Text2Text Generation, Natural Language Processing Sentence Similarity, Audio Text-to-Speech, Audio Automatic Speech Recognition, \
        Audio Audio-to-Audio, Audio Audio Classification, Audio Voice Activity Detection, Tabular Tabular Classification, Tabular Tabular Regression, \
        Reinforcement Learning Reinforcement Learning, Reinforcement Learning Robotics }"
    elif api_name == "tensorhub":
        domains = "1. $DOMAIN is inferred from the task description and should include one of {text-sequence-alignment, text-embedding, text-language-model, text-preprocessing, text-classification, text-generation, text-question-answering, text-retrieval-question-answering, text-segmentation, text-to-mel, image-classification, image-feature-vector, image-object-detection, image-segmentation, image-generator, image-pose-detection, image-rnn-agent, image-augmentation, image-classifier, image-style-transfer, image-aesthetic-quality, image-depth-estimation, image-super-resolution, image-deblurring, image-extrapolation, image-text-recognition, image-dehazing, image-deraining, image-enhancemenmt, image-classification-logits, image-frame-interpolation, image-text-detection, image-denoising, image-others, video-classification, video-feature-extraction, video-generation, video-audio-text, video-text, audio-embedding, audio-event-classification, audio-command-detection, audio-paralinguists-classification, audio-speech-to-text, audio-speech-synthesis, audio-synthesis, audio-pitch-extraction}"
    else:
        print("Error: API name is not supported.")

    prompt = question + "\nWrite a python program in 1 to 2 lines to call API in " + api_name + ".\n\nThe answer should follow the format: <<<domain>>> $DOMAIN, <<<api_call>>>: $API_CALL, <<<api_provider>>>: $API_PROVIDER, <<<explanation>>>: $EXPLANATION, <<<code>>>: $CODE}. Here are the requirements:\n" + domains + "\n2. The $API_CALL should have only 1 line of code that calls api.\n3. The $API_PROVIDER should be the programming framework used.\n4. $EXPLANATION should be a step-by-step explanation.\n5. The $CODE is the python code.\n6. Do not repeat the format in your answer."
    prompts.append({"role": "system", "content": "You are a helpful API writer who can write APIs based on requirements."})
    prompts.append({"role": "user", "content": prompt})
    return prompts

@retry(wait=wait_exponential(multiplier=1, min=10, max=120), reraise=True)
def get_response(get_response_input, api_key):
    question, question_id, api_name, model = get_response_input
    question = encode_question(question, api_name)
    
    try:
        if "gpt" in model:
            openai.api_key = api_key
            responses = openai.ChatCompletion.create(
                model=model,
                messages=question,
                n=1,
                temperature=0,
            )
            response = responses['choices'][0]['message']['content']
        elif "claude" in model:
            client = anthropic.Anthropic(api_key=api_key)
            responses = client.completions.create(
                prompt=f"{anthropic.HUMAN_PROMPT} {question[0]['content']}{question[1]['content']}{anthropic.AI_PROMPT}",
                stop_sequences=[anthropic.HUMAN_PROMPT],
                model="claude-v1",
                max_tokens_to_sample=2048,
            )
            response = responses.completion.strip()
        else:
            print("Error: Model is not supported.")
    except Exception as e:
        print("Error:", e)
        return None
        
    print("=>",)
    return {'text': response, 
            "question_id": question_id,
              "question": question, 
              "answer_id": "None", 
              "model_id": model, "metadata": {}}

def process_entry(entry, api_key):
    question, question_id, api_name, model = entry
    result = get_response((question, question_id, api_name, model), api_key)
    wandb.log({"question_id_completed":question_id})
    return result

def write_result_to_file(result, output_file):
    global file_write_lock
    with file_write_lock:
        with open(output_file, "a") as outfile:
            json.dump(result, outfile)
            outfile.write("\n")

def callback_with_lock(result, output_file):
    global file_write_lock
    write_result_to_file(result, output_file, file_write_lock)

if __name__ == '__main__':
    
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", type=str, default=None, help="which model you want to use for eval, only support ['gpt*', 'claude*'] now")
    parser.add_argument("--api_key", type=str, default=None, help="the api key provided for calling")
    parser.add_argument("--output_file", type=str, default=None, help="the output file this script writes to")
    parser.add_argument("--question_data", type=str, default=None, help="path to the questions data file")
    parser.add_argument("--api_name", type=str, default=None, help="this will be the api dataset name you are testing, only support ['torchhub', 'tensorhun', 'huggingface'] now")
    parser.add_argument("--use_wandb", action='store_true', help="pass this argument to turn on Weights & Biases logging of the LLM responses")
    parser.add_argument("--wandb_project", type=str, default="gorilla-api", help="Weights & Biases project name")
    parser.add_argument("--wandb_entity", type=str, default=None, help="Weights & Biases entity name")
    # Arguments for evaluation
    # parser.add_argument("--evaluation_script", type=str, default="/workspaces/gorilla/eval/eval-scripts/ast_eval_th.py", help="Evaluation script to compute accuracy and hallucination")
    parser.add_argument("--api_dataset", type=str, default=None, help="path to your api dataset")
    parser.add_argument(
        "--apibench",
        type=str,
        default=None,
        help="path to your apibench dataset including the question and answer pairs",
    )
    parser.add_argument("--local", action='store_true', help="pass this argument to run in local mode")
    # parser.add_argument("--llm_responses", type=str, default=argparse.SUPPRESS, help="path to the language model responses")
    # add parser argument for debug flag
    parser.add_argument("--debug", action='store_true', help="pass this argument to turn on debug mode")
    args = parser.parse_args()
    # if args.llm_responses is None:
    args.llm_responses = args.output_file
    # Only for debugging - set to true, so we can use the debugger
    # args.local = True
    if args.local:
        print("Running in debug mode")
        args.model = "gpt-3.5-turbo"
        # args.api_key = ""
        args.output_file = "/workspaces/gorilla/eval/gpt-3.5-turbo_torchhub_0_shot_temp.jsonl"
        args.question_data = "/workspaces/gorilla/eval/eval-data/questions/torchhub/questions_torchhub_0_shot.jsonl"
        args.api_name = "torchhub"
        args.use_wandb = True
        args.wandb_project = "FunctionCalling"
        args.wandb_entity = "jazz-benchmark"
        args.api_dataset = "/workspaces/gorilla/data/api/torchhub_api.jsonl"
        args.apibench = "/workspaces/gorilla/data/apibench/torchhub_eval.json"
        args.debug = True
        args.llm_responses = "/workspaces/gorilla/eval/gpt-3.5-turbo_torchhub_0_shot.jsonl"
    if args.use_wandb:
        wandb.init(
            project=args.wandb_project, 
            entity=args.wandb_entity,
            name=f"{args.model}-{args.api_name}-{args.question_data}-{args.output_file}",
            config={
                "api_name": args.api_name,
                "model": args.model,
                "question_data": args.question_data,
                "output_file": args.output_file,
                "api_dataset": args.api_dataset,
                "apibench": args.apibench,
                "llm_responses": args.llm_responses,
            }
        )

    start_time = time.time()
    # Read the question file
    questions = []
    question_ids = []
    with open(args.question_data, 'r') as f:
        for idx, line in enumerate(f):
            questions.append(json.loads(line)["text"])
            question_ids.append(json.loads(line)["question_id"])
    # check if debug was passed 
    if args.debug:
        questions = questions[:10]
        question_ids = question_ids[:10]

    if os.path.exists(args.output_file):
        print(f"\nExisting responses file found at: {args.output_file}, deleting it ...\n")
        os.remove(args.output_file)

    file_write_lock = mp.Lock()
    with mp.Pool(1) as pool:
        results = []
        for idx, (question, question_id) in enumerate(zip(questions, question_ids)):
            result = pool.apply_async(
                process_entry,
                args=((question, question_id, args.api_name, args.model), args.api_key),
                callback=lambda result: write_result_to_file(result, args.output_file),
            )
            results.append(result)
        pool.close()
        pool.join()

    end_time = time.time()
    elapsed_time = end_time - start_time
    print("Total time used: ", elapsed_time)

    # Run the evaluation pipeline
    if args.api_name == "torchhub":
        # debuggig purposes
        ast_eval_th = import_module("eval-scripts.ast_eval_th")
        main = ast_eval_th.main
        args_evaluation = argparse.Namespace(
            api_dataset=args.api_dataset,
            apibench=args.apibench,
            llm_responses=args.output_file,
        )
        evaluation_output_dict = main(args_evaluation)

        # args_evaluation = parser.parse_args()
        # # parser_evaluation = argparse.ArgumentParser()
        # args_evaluation.api_dataset = args.api_dataset
        # args_evaluation.apibench = args.apibench
        # args_evaluation.llm_responses = args.output_file
        # main(args_evaluation)

    # Run the script and capture the output
    # result = subprocess.run(
    #     ["python", args.evaluation_script, "--api_dataset", args.api_dataset, "--apibench", args.apibench, "--llm_responses", args.llm_responses],
    #     check=True,
    #     text=True,
    #     capture_output=True
    # )

    # evaluation_output_lines = result.stdout.split("\n")
    # evaluation_output_dict = {line.split(": ")[0]: float(line.split(": ")[1]) for line in evaluation_output_lines if line}

    # print(evaluation_output_dict)

    if args.use_wandb:
        print("\nSaving all responses to Weights & Biases...\n")
        wandb.summary["elapsed_time_s"] = elapsed_time
        wandb.log({"elapsed_time_s":elapsed_time})

        line_count = 0 
        with open(args.output_file, 'r') as file:
            for i,line in enumerate(file):
                data = json.loads(line.strip())

                if i == 0:
                    tbl = wandb.Table(columns=list(data.keys()))
                if data is not None:
                    tbl.add_data(*list(data.values()))
                    line_count+=1
        
        # Log the Tale to W&B
        wandb.log({"llm_eval_responses": tbl})
        wandb.summary["response_count"] = line_count

        # log evaluation_output_dict in wandb too and display as table
        wandb.log(evaluation_output_dict)
        # Create a new table
        table_evaluation = wandb.Table(data=list(evaluation_output_dict.items()), columns=["Key", "Value"])

        # Log the table
        wandb.log({"Evaluation Output": table_evaluation})

        # Also log results file as W&B Artifact
        artifact_model_name = re.sub(r'[^a-zA-Z0-9-_.]', '-', args.model)
        wandb.log_artifact(args.output_file, 
            name=f"{args.api_name}-{artifact_model_name}-eval-responses", 
            # name=f"{args.model}-{args.api_name}-{args.question_data}-{args.output_file}",
            type=f"eval-responses", 
            aliases=[f"{line_count}-responses"]
        )
        wandb.finish()
