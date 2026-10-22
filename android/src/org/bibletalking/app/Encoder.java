package org.bibletalking.app;

import ai.onnxruntime.*;
import java.io.*;
import java.util.*;

public final class Encoder implements AutoCloseable {
    final BertTokenizer tokenizer;
    private final OrtEnvironment env=OrtEnvironment.getEnvironment();
    private final OrtSession session;
    public Encoder(String model, InputStream vocab) throws Exception {
        tokenizer=new BertTokenizer(vocab);
        try(OrtSession.SessionOptions options=new OrtSession.SessionOptions()) {
            options.setIntraOpNumThreads(2); options.setInterOpNumThreads(1);
            session=env.createSession(model,options);
        }
    }
    public float[] encode(String text) throws Exception {
        long[] ids=tokenizer.encode(text), mask=new long[ids.length];Arrays.fill(mask,1);
        try(OnnxTensor input=OnnxTensor.createTensor(env,new long[][]{ids});
            OnnxTensor attention=OnnxTensor.createTensor(env,new long[][]{mask});
            OnnxTensor types=OnnxTensor.createTensor(env,new long[][]{new long[ids.length]})) {
            Map<String,OnnxTensor> inputs=new HashMap<>(); inputs.put("input_ids",input);
            if(session.getInputNames().contains("attention_mask")) inputs.put("attention_mask",attention);
            if(session.getInputNames().contains("token_type_ids")) inputs.put("token_type_ids",types);
            try(OrtSession.Result result=session.run(inputs)) {
                Object output=result.get(0).getValue();
                float[] vector=output instanceof float[][][]?((float[][][])output)[0][0]:((float[][])output)[0];
                double norm=0;for(float x:vector)norm+=x*x;norm=Math.sqrt(norm);
                for(int i=0;i<vector.length;i++)vector[i]/=norm;return vector;
            }
        }
    }
    public void close() throws Exception { session.close(); }
}
