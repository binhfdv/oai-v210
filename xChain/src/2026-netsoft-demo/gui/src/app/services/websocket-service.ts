import { Injectable } from '@angular/core';
import io from 'socket.io-client';
import { Observable } from 'rxjs';
import { Statistic } from '../models/chart_data.mode';
import { environment } from '../../environments/environment';

@Injectable({
  providedIn: 'root'
})
export class WebsocketService {
  private socket = io(environment.apiUrl);

  // sendMessage(message: string): void {
  //   this.socket.emit('stats', message);
  // }

  // getMessages(): Observable<Statistic> {
  //   return new Observable((observer) => {
  //     this.socket.on('statistics', (message) => {
  //       observer.next(message);
  //     });
  //   });
  // }

  listenOnMessages<T>(topic:string): Observable<T> {
    return new Observable((observer) => {
      this.socket.on(topic, (message) => {
        observer.next(message);
      });
    });
  }
    // Close the WebSocket connection
  disconnect(): void {
    this.socket.close();
  }
}