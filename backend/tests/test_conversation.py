def test_conversation_proposes_and_confirms_order(client):
    proposal = client.post("/api/configurations/converse", json={
        "message": "I want a blue fan", "configuration": {}, "history": []
    })
    assert proposal.status_code == 200
    assert proposal.json()["configuration"] == {"color": "blue"}
    assert proposal.json()["requires_confirmation"] is True
    confirmation = client.post("/api/configurations/converse", json={
        "message": "Yes, confirm it",
        "current_configuration": proposal.json()["configuration"],
        "confirmed": True,
    })
    assert confirmation.status_code == 200
    assert confirmation.json()["order_id"] is not None
    assert confirmation.json()["requires_confirmation"] is False
