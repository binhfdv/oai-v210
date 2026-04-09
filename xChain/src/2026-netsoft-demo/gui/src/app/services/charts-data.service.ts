import { Injectable, signal } from '@angular/core';
import { ChartDataItem, Statistic } from '../models/chart_data.mode';
import { Observable, Subject } from 'rxjs';
import { HttpClient } from '@angular/common/http';
import { environment } from '../../environments/environment';
@Injectable({
  providedIn: 'root'
})
export class ChartsDataService {
  timer:any;
  
  constructor(private http: HttpClient) {}
  
  
  startTimer() {
    this.timer = setInterval(() => {
      this.getStatistics();
    },1000)
  }
  
  pauseTimer() {
    clearInterval(this.timer);
  }
  
  getStatistics() {
    console.log("getting statistics");
    let res= this.http.get<Statistic>(environment.apiUrl+'stats');
    console.log(res);
    
    return res;
    
    //   Observable.interval(3000)
    //         .timeInterval()
    //         .flatMap(() => this.http.request('http://mywebserver.com/apps/random.php')
    //         .map(res=> res.json())
  }
}
