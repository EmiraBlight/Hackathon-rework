import asyncio
import websockets
import json
import uuid
import random
from google import genai
GAMES = dict()
PLAYERS =  dict()

async def get_ai_answer(client, prompt):

    response = await client.aio.models.generate_content(
        model="gemma-3-1b-it",
        contents=f"{prompt} answer in under 2 sentences",
    )
    return response.text
async def get_random_prompts():
    result = {}
    try:
        with open('prompts.json', 'r') as file:
            data = json.load(file)
        questions = random.sample(data["questions"], 3)
    except (FileNotFoundError, KeyError) as e:
        print(f"Error loading prompts: {e}")
        return None

    selected_indices = random.sample(range(3), 2)
    all_indices = {0, 1, 2}
    blank_index = list(all_indices - set(selected_indices))[0]

    client = genai.Client()

    task1 = get_ai_answer(client, questions[selected_indices[0]])
    task2 = get_ai_answer(client, questions[selected_indices[1]])

    answers = await asyncio.gather(task1, task2)

    result[questions[selected_indices[0]]] = answers[0]
    result[questions[selected_indices[1]]] = answers[1]


    result[questions[blank_index]] = ""
    result["blank"] = questions[blank_index]

    return result

async def handler(websocket):
    current_game_id = None
    try:
        async for message in websocket:
            data = json.loads(message)
            msg_type = data.get("type")

            if msg_type == "create":
                game_id = str(uuid.uuid4())[:8]
                GAMES[game_id] = [websocket]
                current_game_id = game_id
                await websocket.send(json.dumps({"type": "game_created", "id": game_id}))

            elif msg_type == "join":
                game_id = data.get("id", None)
                if game_id in GAMES:
                    GAMES[game_id].append(websocket)
                    current_game_id = game_id

                    if len(GAMES[game_id]) == 2:
                        print(f"Game {game_id} is full. Generating prompts...")

                        for player_ws in GAMES[game_id]:
                            # Generate unique prompts for each player
                            prompts = await get_random_prompts()
                            PLAYERS[player_ws] = {
                                "prompts": prompts,
                                "response": None,
                                "game_id": game_id
                            }

                            await player_ws.send(json.dumps({
                                "type": "prompts",
                                "data": prompts
                            }))

                    if len(GAMES[game_id]) > 2:
                        await websocket.send(json.dumps({
                            "type": "refused",
                            "message": "Game full"
                        }))
                        return
                    else:
                        await websocket.send(json.dumps({
                            "type": "info",
                            "message": "Waiting for another player to join..."
                        }))
                else:
                    await websocket.send(json.dumps({"type": "error", "message": "Game not found"}))

            if msg_type == "response":
                user_response = data.get("text", "")
                print("Got response")
                # Save the response for this specific player
                if websocket in PLAYERS:
                    PLAYERS[websocket]["response"] = user_response

                    # Check if everyone in THIS game is done
                    game_participants = GAMES.get(current_game_id, [])
                    all_done = all(
                        PLAYERS.get(ws, {}).get("response") is not None
                        for ws in game_participants
                    )

                    if all_done:
                        if all_done:
                                                # 1. Compile the full data for every player in this game
                                final_reveal = []
                                for ws in game_participants:
                                    player_data = PLAYERS[ws]
                                    prompts = player_data["prompts"] # The dict from get_random_prompts
                                    user_answer = player_data["response"]

                                                    # Merge the user's answer into the blank prompt spot
                                    blank_key = prompts.get("blank")
                                    prompts[blank_key] = user_answer

                                    final_reveal.append({
                                        "player": f"Player {game_participants.index(ws) + 1}",
                                        "full_set": prompts # Now contains 2 AI answers and 1 User answer
                                    })

                                                # 2. Send the whole bundle to everyone
                                broadcast_payload = json.dumps({
                                    "type": "results",
                                    "data": final_reveal
                                })

                                await asyncio.gather(*(ws.send(broadcast_payload) for ws in game_participants))

                                                # 3. Optional: Reset the responses so they can play again
                                for ws in game_participants:
                                    PLAYERS[ws]["response"] = None
                    else:
                        await websocket.send(json.dumps({"type": "status", "data": "Waiting on others..."}))
                else:
                    await websocket.send(json.dumps({"type": "error", "message": "Game not found"}))


    except websockets.exceptions.ConnectionClosed:
        pass
    finally:
        if current_game_id in GAMES and websocket in GAMES[current_game_id]:
            GAMES[current_game_id].remove(websocket)
        if websocket in PLAYERS:
            del PLAYERS[websocket]
        print("Client left.")

async def main():
    async with websockets.serve(handler, "localhost", 8765):
        print("Broadcast Server started...")
        await asyncio.Future()

if __name__ == "__main__":
    asyncio.run(main())
