def login_test_client(client):
    response=client.post('/api/auth/login',json={'username':'ailifelab','password':'66666666'})
    assert response.status_code==200,response.text
    response=client.put('/api/auth/model-key',json={'api_key':'sk-test-key-placeholder'})
    assert response.status_code==200,response.text
