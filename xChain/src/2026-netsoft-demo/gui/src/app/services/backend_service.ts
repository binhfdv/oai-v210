import { Injectable, signal } from '@angular/core';
import { ChartDataItem, Statistic } from '../models/chart_data.mode';
import { Observable, Subject } from 'rxjs';
import { HttpClient } from '@angular/common/http';
import { environment } from '../../environments/environment';
@Injectable({
    providedIn: 'root'
})
export class BackendService {
    
    
    constructor(private http: HttpClient) {}
    
    start(scenario:string,traffic_type:string){
        console.log("sending start Command", environment.apiUrl);
        let res= this.http.post(
                                environment.apiUrl+'start',{
                                "models":scenario,
                                "traffic_type":traffic_type
                            });
        console.log(res);
        
        return res;

    }
    stop(){
        console.log("sending stop Command", environment.apiUrl);
        let res= this.http.get( environment.apiUrl+'stop');
        console.log(res);
        return res;

    } 
}