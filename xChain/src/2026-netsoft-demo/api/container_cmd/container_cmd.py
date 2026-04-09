import socket
import signal
import subprocess
import os
import sys
import threading
import time

process_id=-1
current_command=0
connected=False
client_socket = socket.socket()  # instantiate 
def handle_msg(input):
    global current_command
    global process_id
    try:
        if len(input) < 4:
             return        
        input_array=input.split(":")
        received_command=input_array[0].upper()
        current_command=received_command
        print("handle_msg",received_command)
        if received_command == 'START':
                    received_command_params=input_array[1]
                    print("from connected user: ", received_command)
                    print("parameters " ,input_array)
             
                    
                    print("COMMAND " ,received_command_params)

                    # stop the current process
                    if process_id != -1:
                        kill_current_process()
                    client_thread = threading.Thread(target=run_command,args=(received_command_params,))
                    client_thread.start()
                    
        elif received_command == 'STOP':
                    print("stoping")
                    kill_current_process() 
                    # os.killpg(os.getpgid(process_id.pid), signal.SIGTERM)     
        else:
                    print("Unknown command:",received_command)
                      
    
    except socket.error:
        print("server is not reachable")
    except Exception as e:
        print(e)

def kill_current_process():
    try:
        global process_id
        if process_id ==-1:
            return
        print("killing",process_id)
        process_id.kill()
        os.kill(process_id.pid, signal.SIGTERM)  
        process_id=-1
    except Exception:
          process_id=-1
          print("Process is not exist")



def run_command(received_command_params):
        global process_id
        received_command_params=received_command_params.split(" ")
        with subprocess.Popen(received_command_params, stdout=subprocess.PIPE, bufsize=1, universal_newlines=True) as proc:
                        process_id= proc
                        for line in proc.stdout:
                            if current_command == 'STOP':
                                 print("command stoppped ------- ")
                                 break
                            print(line, end='') # process line here
        kill_current_process()
host = ""  # as both code is running on same pc
port = 4000  # socket server port number
def client_program():
    global connected
    global client_socket

    while not connected:
        try:
            print("Trying to connect to host",host,"port",port)
            client_socket = socket.socket()  # instantiate        
            client_socket.connect((host, port))  # connect to the server
            connected = True
            message = socket.gethostname()
            client_socket.send(message.encode())

            keepalive_thread = threading.Thread(target=send_alive_signal,args=())
            keepalive_thread.start()  

        except socket.error:
            time.sleep(2)

    while True:
        try:            
            data = client_socket.recv(1024).decode()  # receive response
            if not data:
                break
            print('Received from server: ' + data)  # show in terminal
            handle_msg(data)
        except socket.error:
              print("ffdsfsd")

def send_alive_signal():
    global connected
    print("sen keep")
    if connected:
        while True:
            time.sleep(5) 

            try:
                print("sending keep alive signal")            
                message = "1"
                client_socket.send(message.encode())
                # time.sleep(2) 
            except socket.error:
                print("connection lost")
                connected = False
                break
    client_program()
      
if __name__ == '__main__':
    host=sys.argv[1:][0]
    port=int(sys.argv[1:][1])
    print("host",host,"port",port)
    try:
        client_program()
    except Exception as e:
         print("main exp",e)    
