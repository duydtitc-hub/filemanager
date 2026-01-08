from convert_stt import has_segment_over_1_minute
sample = [{'start': {'Phut':0,'Giay':10,'miligiay':0}, 'end': {'Phut':1,'Giay':11,'miligiay':0}}]
print(has_segment_over_1_minute(sample))
