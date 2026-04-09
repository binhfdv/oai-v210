import time
file1 = open("myfile.txt", "w")
while True:
    current_time = time.strftime("%H:%M:%S")
    print(f"Current time: {current_time}")
    with open("test.txt", "a") as myfile:
        myfile.write("\n" +current_time)
    time.sleep(5)


